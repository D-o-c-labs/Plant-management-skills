"""Plant, location, microzone, and irrigation system CRUD operations.

All mutations go through store.write() for atomic writes + schema validation.
"""

import json

from . import store


# ---------------------------------------------------------------------------
# Plants
# ---------------------------------------------------------------------------

def list_plants(*, status=None, location=None):
    """List plants, optionally filtered by status and/or location."""
    data = store.read("plants.json")
    plants = data["plants"]
    if status:
        plants = [p for p in plants if p["status"] == status]
    if location:
        plants = [p for p in plants if p["locationId"] == location]
    return plants


def get_plant(plant_id):
    """Get a single plant by ID. Returns None if not found."""
    data = store.read("plants.json")
    for p in data["plants"]:
        if p["plantId"] == plant_id:
            return p
    return None


def _compute_irrigation_effective_state(plant):
    """Derive the denormalized irrigation state from plant and system data."""
    if plant.get("attachedToIrrigation") and plant.get("irrigationSystemId"):
        irrigation_system = get_irrigation_system(plant["irrigationSystemId"])
        if irrigation_system and irrigation_system.get("enabled"):
            return "active"
        return "attached_but_system_off"
    if plant.get("irrigationMode") == "manual":
        return "manual_only"
    return "not_attached"


def _refresh_irrigation_state(plant):
    updated = dict(plant)
    updated["irrigationEffectiveState"] = _compute_irrigation_effective_state(updated)
    return updated


def add_plant(*, name, location_id, sublocation_id=None, species=None,
              scientific_name=None, indoor_outdoor="outdoor",
              irrigation_mode="manual", irrigation_system_id=None,
              attached_to_irrigation=False, notes=None, **extra):
    """Add a new plant to the registry. Returns the created plant."""
    # Verify location exists
    _require_location(location_id)
    if sublocation_id:
        _require_microzone(sublocation_id, location_id)
    if irrigation_system_id:
        _require_irrigation_system(irrigation_system_id)

    data = store.read("plants.json")
    numeric_id = data["nextPlantNumericId"]
    plant_id = f"plant_{numeric_id:03d}"

    plant = {
        "plantId": plant_id,
        "displayName": name,
        "speciesCommonName": species,
        "speciesScientificName": scientific_name,
        "speciesConfidence": "known" if species else "unknown",
        "status": "active",
        "locationId": location_id,
        "subLocationId": sublocation_id,
        "indoorOutdoor": indoor_outdoor,
        "irrigationMode": irrigation_mode,
        "irrigationSystemId": irrigation_system_id,
        "attachedToIrrigation": attached_to_irrigation,
        "irrigationEffectiveState": None,
        "wateringProfileId": None,
        "notes": notes,
        "riskFlags": [],
        "fertilizationProfileId": None,
        "repottingProfileId": None,
        "pestProfileId": None,
        "maintenanceProfileId": None,
        "healthCheckProfileId": None,
    }
    # Apply any extra fields
    for k, v in extra.items():
        if k not in plant:
            plant[k] = v

    plant = _refresh_irrigation_state(plant)

    data["plants"].append(plant)
    data["nextPlantNumericId"] = numeric_id + 1
    store.write("plants.json", data)
    return plant


def update_plant(plant_id, updates):
    """Update fields on an existing plant. Returns the updated plant."""
    data = store.read("plants.json")
    for i, p in enumerate(data["plants"]):
        if p["plantId"] == plant_id:
            # Validate referential integrity for location/irrigation changes
            if "locationId" in updates:
                _require_location(updates["locationId"])
            if "subLocationId" in updates and updates["subLocationId"]:
                loc = updates.get("locationId", p["locationId"])
                _require_microzone(updates["subLocationId"], loc)
            if "irrigationSystemId" in updates and updates["irrigationSystemId"]:
                _require_irrigation_system(updates["irrigationSystemId"])

            merged = {**p, **updates}
            data["plants"][i] = _refresh_irrigation_state(merged)
            store.write("plants.json", data)
            return data["plants"][i]
    raise ValueError(f"Plant not found: {plant_id}")


def archive_plant(plant_id, reason=None):
    """Archive a plant (set status to 'archived')."""
    updates = {"status": "archived"}
    if reason:
        updates["notes"] = reason
    return update_plant(plant_id, updates)


def move_plant(plant_id, location_id, sublocation_id=None):
    """Move a plant to a new location."""
    updates = {"locationId": location_id, "subLocationId": sublocation_id}
    return update_plant(plant_id, updates)


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def list_locations():
    data = store.read("locations.json")
    return data["locations"]


def get_location(location_id):
    data = store.read("locations.json")
    for loc in data["locations"]:
        if loc["locationId"] == location_id:
            return loc
    return None


def add_location(*, location_id, name, loc_type, indoor_outdoor="indoor",
                 exposure=None, notes=None, **extra):
    """Add a new location."""
    data = store.read("locations.json")
    # Check for duplicates
    if any(l["locationId"] == location_id for l in data["locations"]):
        raise ValueError(f"Location already exists: {location_id}")

    location = {
        "locationId": location_id,
        "displayName": name,
        "type": loc_type,
        "indoorOutdoor": indoor_outdoor,
        "exposure": exposure or "unknown",
        "sunWindowDescription": "",
        "windExposure": "unknown",
        "rainExposure": "unknown" if indoor_outdoor == "outdoor" else "none",
        "notes": notes or "",
    }
    for k, v in extra.items():
        if k not in location:
            location[k] = v

    data["locations"].append(location)
    store.write("locations.json", data)
    return location


def update_location(location_id, updates):
    """Update fields on an existing location."""
    data = store.read("locations.json")
    for i, loc in enumerate(data["locations"]):
        if loc["locationId"] == location_id:
            data["locations"][i] = {**loc, **updates}
            store.write("locations.json", data)
            return data["locations"][i]
    raise ValueError(f"Location not found: {location_id}")


# ---------------------------------------------------------------------------
# Microzones
# ---------------------------------------------------------------------------

def list_microzones(*, location=None):
    data = store.read("microzones.json")
    zones = data["microzones"]
    if location:
        zones = [z for z in zones if z["locationId"] == location]
    return zones


def get_microzone(microzone_id):
    data = store.read("microzones.json")
    for z in data["microzones"]:
        if z["microzoneId"] == microzone_id:
            return z
    return None


def add_microzone(*, microzone_id, location_id, name, **extra):
    """Add a new microzone."""
    _require_location(location_id)
    data = store.read("microzones.json")
    if any(z["microzoneId"] == microzone_id for z in data["microzones"]):
        raise ValueError(f"Microzone already exists: {microzone_id}")

    zone = {
        "microzoneId": microzone_id,
        "locationId": location_id,
        "displayName": name,
        "lightClass": "unknown",
        "heatLoad": "unknown",
        "dryingSpeed": "unknown",
        "windExposure": "unknown",
        "runoffSensitivity": "unknown",
        "notes": "",
    }
    for k, v in extra.items():
        if k not in zone:
            zone[k] = v
        else:
            zone[k] = v

    data["microzones"].append(zone)
    store.write("microzones.json", data)
    return zone


def update_microzone(microzone_id, updates):
    """Update fields on an existing microzone."""
    data = store.read("microzones.json")
    for i, z in enumerate(data["microzones"]):
        if z["microzoneId"] == microzone_id:
            data["microzones"][i] = {**z, **updates}
            store.write("microzones.json", data)
            return data["microzones"][i]
    raise ValueError(f"Microzone not found: {microzone_id}")


# ---------------------------------------------------------------------------
# Irrigation Systems
# ---------------------------------------------------------------------------

def list_irrigation_systems():
    data = store.read("irrigation_systems.json")
    return data["irrigationSystems"]


def get_irrigation_system(system_id):
    data = store.read("irrigation_systems.json")
    for s in data["irrigationSystems"]:
        if s["irrigationSystemId"] == system_id:
            return s
    return None


def update_irrigation_system(system_id, updates):
    """Update fields on an existing irrigation system."""
    data = store.read("irrigation_systems.json")
    for i, s in enumerate(data["irrigationSystems"]):
        if s["irrigationSystemId"] == system_id:
            data["irrigationSystems"][i] = {**s, **updates}
            store.write("irrigation_systems.json", data)
            _recompute_plants_for_irrigation_system(system_id)
            return data["irrigationSystems"][i]
    raise ValueError(f"Irrigation system not found: {system_id}")


def _recompute_plants_for_irrigation_system(system_id):
    """Refresh denormalized irrigation state for plants attached to a system."""
    plants_data = store.read("plants.json")
    changed = False
    for index, plant in enumerate(plants_data["plants"]):
        if plant.get("irrigationSystemId") != system_id:
            continue
        refreshed = _refresh_irrigation_state(plant)
        if refreshed.get("irrigationEffectiveState") != plant.get("irrigationEffectiveState"):
            plants_data["plants"][index] = refreshed
            changed = True

    if changed:
        store.write("plants.json", plants_data)


# ---------------------------------------------------------------------------
# Referential integrity helpers
# ---------------------------------------------------------------------------

def _require_location(location_id):
    if not get_location(location_id):
        raise ValueError(f"Location does not exist: {location_id}")


def _require_microzone(microzone_id, expected_location_id=None):
    zone = get_microzone(microzone_id)
    if not zone:
        raise ValueError(f"Microzone does not exist: {microzone_id}")
    if expected_location_id and zone["locationId"] != expected_location_id:
        raise ValueError(
            f"Microzone {microzone_id} belongs to {zone['locationId']}, "
            f"not {expected_location_id}"
        )


def _require_irrigation_system(system_id):
    if not get_irrigation_system(system_id):
        raise ValueError(f"Irrigation system does not exist: {system_id}")


# ---------------------------------------------------------------------------
# CLI handlers
# ---------------------------------------------------------------------------

def _format_plant_row(p):
    status_icons = {"active": "+", "recovering": "~", "archived": "-", "dead": "x"}
    icon = status_icons.get(p["status"], "?")
    irr = p.get("irrigationEffectiveState", "")
    loc = p.get("subLocationId") or p["locationId"]
    return f"  [{icon}] {p['plantId']:>10}  {p['displayName']:<25} {loc:<30} {irr}"


def cli_plants(args):
    as_json = getattr(args, "json", False)
    subcmd = args.subcmd

    if subcmd == "list":
        plants = list_plants(
            status=getattr(args, "status", None),
            location=getattr(args, "location", None),
        )
        if as_json:
            print(json.dumps(plants, indent=2, ensure_ascii=False))
        else:
            if not plants:
                print("No plants found.")
                return
            print(f"{'':2} {'ID':>10}  {'Name':<25} {'Location':<30} Irrigation")
            print("-" * 85)
            for p in plants:
                print(_format_plant_row(p))
            print(f"\n{len(plants)} plant(s)")

    elif subcmd == "get":
        plant = get_plant(args.plantId)
        if plant:
            print(json.dumps(plant, indent=2, ensure_ascii=False))
        else:
            print(f"Plant not found: {args.plantId}")

    elif subcmd == "add":
        plant = add_plant(
            name=args.name,
            location_id=args.location,
            sublocation_id=getattr(args, "sublocation", None),
            species=getattr(args, "species", None),
            scientific_name=getattr(args, "scientific_name", None),
            indoor_outdoor=getattr(args, "indoor_outdoor", "outdoor"),
            irrigation_mode=getattr(args, "irrigation_mode", "manual"),
            irrigation_system_id=getattr(args, "irrigation_system", None),
            attached_to_irrigation=getattr(args, "attached_to_irrigation", False),
            notes=getattr(args, "notes", None),
        )
        if as_json:
            print(json.dumps(plant, indent=2, ensure_ascii=False))
        else:
            print(f"Created: {plant['plantId']} ({plant['displayName']})")

    elif subcmd == "update":
        updates = json.loads(args.data)
        plant = update_plant(args.plantId, updates)
        if as_json:
            print(json.dumps(plant, indent=2, ensure_ascii=False))
        else:
            print(f"Updated: {plant['plantId']}")

    elif subcmd == "archive":
        plant = archive_plant(args.plantId, getattr(args, "reason", None))
        print(f"Archived: {plant['plantId']}")

    elif subcmd == "move":
        plant = move_plant(args.plantId, args.location, getattr(args, "sublocation", None))
        if as_json:
            print(json.dumps(plant, indent=2, ensure_ascii=False))
        else:
            loc = plant.get("subLocationId") or plant["locationId"]
            print(f"Moved {plant['plantId']} → {loc}")

    else:
        print("Usage: plant_mgmt plants {list|get|add|update|archive|move}")


def cli_locations(args):
    as_json = getattr(args, "json", False)
    subcmd = args.subcmd

    if subcmd == "list":
        locs = list_locations()
        if as_json:
            print(json.dumps(locs, indent=2, ensure_ascii=False))
        else:
            for loc in locs:
                print(f"  {loc['locationId']:<25} {loc['displayName']:<25} {loc['type']:<10} {loc['indoorOutdoor']}")

    elif subcmd == "get":
        loc = get_location(args.locationId)
        if loc:
            print(json.dumps(loc, indent=2, ensure_ascii=False))
        else:
            print(f"Location not found: {args.locationId}")

    elif subcmd == "add":
        loc = add_location(
            location_id=args.id,
            name=args.name,
            loc_type=args.type,
            indoor_outdoor=getattr(args, "indoor_outdoor", "indoor"),
            exposure=getattr(args, "exposure", None),
            notes=getattr(args, "notes", None),
        )
        if as_json:
            print(json.dumps(loc, indent=2, ensure_ascii=False))
        else:
            print(f"Created: {loc['locationId']}")

    elif subcmd == "update":
        updates = json.loads(args.data)
        loc = update_location(args.locationId, updates)
        if as_json:
            print(json.dumps(loc, indent=2, ensure_ascii=False))
        else:
            print(f"Updated: {loc['locationId']}")

    else:
        print("Usage: plant_mgmt locations {list|get|add|update}")


def cli_microzones(args):
    as_json = getattr(args, "json", False)
    subcmd = args.subcmd

    if subcmd == "list":
        zones = list_microzones(location=getattr(args, "location", None))
        if as_json:
            print(json.dumps(zones, indent=2, ensure_ascii=False))
        else:
            for z in zones:
                print(f"  {z['microzoneId']:<35} {z['displayName']:<30} light={z.get('lightClass','?')}")

    elif subcmd == "add":
        extra = {}
        if getattr(args, "data", None):
            extra = json.loads(args.data)
        zone = add_microzone(
            microzone_id=args.id,
            location_id=args.location,
            name=args.name,
            **extra,
        )
        if as_json:
            print(json.dumps(zone, indent=2, ensure_ascii=False))
        else:
            print(f"Created: {zone['microzoneId']}")

    elif subcmd == "update":
        updates = json.loads(args.data)
        zone = update_microzone(args.microzoneId, updates)
        if as_json:
            print(json.dumps(zone, indent=2, ensure_ascii=False))
        else:
            print(f"Updated: {zone['microzoneId']}")

    else:
        print("Usage: plant_mgmt microzones {list|add|update}")


def cli_irrigation(args):
    as_json = getattr(args, "json", False)
    subcmd = args.subcmd

    if subcmd == "list":
        systems = list_irrigation_systems()
        if as_json:
            print(json.dumps(systems, indent=2, ensure_ascii=False))
        else:
            for s in systems:
                enabled = "ON" if s.get("enabled") else "OFF"
                print(f"  {s['irrigationSystemId']:<35} {s['locationId']:<20} {enabled}")

    elif subcmd == "get":
        sys = get_irrigation_system(args.systemId)
        if sys:
            print(json.dumps(sys, indent=2, ensure_ascii=False))
        else:
            print(f"Irrigation system not found: {args.systemId}")

    elif subcmd == "update":
        updates = json.loads(args.data)
        sys = update_irrigation_system(args.systemId, updates)
        if as_json:
            print(json.dumps(sys, indent=2, ensure_ascii=False))
        else:
            print(f"Updated: {sys['irrigationSystemId']}")

    else:
        print("Usage: plant_mgmt irrigation {list|get|update}")
