"""Profile management for all care types: watering, fertilization, repotting, pest, maintenance, healthcheck."""

import json
from . import store


# Map profile type names to filenames
PROFILE_FILES = {
    "watering": "watering_profiles.json",
    "fertilization": "fertilization_profiles.json",
    "repotting": "repotting_profiles.json",
    "pest": "pest_profiles.json",
    "maintenance": "maintenance_profiles.json",
    "healthcheck": "healthcheck_profiles.json",
}

PROFILE_PLANT_FIELDS = {
    "watering": "wateringProfileId",
    "fertilization": "fertilizationProfileId",
    "repotting": "repottingProfileId",
    "pest": "pestProfileId",
    "maintenance": "maintenanceProfileId",
    "healthcheck": "healthCheckProfileId",
}


def _get_filename(profile_type):
    filename = PROFILE_FILES.get(profile_type)
    if not filename:
        raise ValueError(
            f"Unknown profile type: {profile_type}. "
            f"Valid types: {', '.join(PROFILE_FILES.keys())}"
        )
    return filename


def list_profiles(profile_type, *, plant_id=None):
    """List profiles of a given type, optionally filtered by plant."""
    filename = _get_filename(profile_type)
    data = store.read(filename)
    profiles = data["profiles"]
    if plant_id:
        profiles = [p for p in profiles if p["plantId"] == plant_id]
    return profiles


def get_profile(profile_type, identifier):
    """Get a single profile by profileId or plantId. Returns None if not found."""
    filename = _get_filename(profile_type)
    data = store.read(filename)
    for p in data["profiles"]:
        if p.get("profileId") == identifier or p["plantId"] == identifier:
            return p
    return None


def set_profile(profile_type, plant_id, profile_data):
    """Set (create or update) a profile for a plant.

    profile_data should be a dict with profile fields.
    plantId and displayName are added/overwritten automatically.
    """
    from . import registry

    profile_data = dict(profile_data)

    # Verify plant exists
    plant = registry.get_plant(plant_id)
    if not plant:
        raise ValueError(f"Plant not found: {plant_id}")

    filename = _get_filename(profile_type)
    data = store.read(filename)

    existing = get_profile(profile_type, profile_data.get("profileId") or plant_id)
    profile_id = profile_data.get("profileId")
    if not profile_id and existing:
        profile_id = existing.get("profileId")
    if not profile_id:
        profile_id = plant_id

    # Ensure plantId, profileId, and displayName are set
    profile_data["plantId"] = plant_id
    profile_data["profileId"] = profile_id
    profile_data["displayName"] = plant.get("displayName", plant_id)

    # Find existing profile or append
    found = False
    for i, p in enumerate(data["profiles"]):
        if p.get("profileId") == profile_id or p["plantId"] == plant_id:
            data["profiles"][i] = {**p, **profile_data}
            found = True
            break

    if not found:
        data["profiles"].append(profile_data)

    store.write(filename, data)
    _link_profile_to_plant(profile_type, plant_id, profile_id)
    return get_profile(profile_type, profile_id)


def remove_profile(profile_type, identifier):
    """Remove a profile by profileId or plantId. Returns True if removed, False if not found."""
    from . import registry

    filename = _get_filename(profile_type)
    data = store.read(filename)

    removed_profile = None
    kept_profiles = []
    for profile in data["profiles"]:
        if profile.get("profileId") == identifier or profile["plantId"] == identifier:
            removed_profile = profile
            continue
        kept_profiles.append(profile)

    if removed_profile:
        data["profiles"] = kept_profiles
        store.write(filename, data)
        field_name = PROFILE_PLANT_FIELDS[profile_type]
        plant = registry.get_plant(removed_profile["plantId"])
        if plant and plant.get(field_name) == removed_profile.get("profileId", removed_profile["plantId"]):
            registry.update_plant(removed_profile["plantId"], {field_name: None})
        return True
    return False


def _link_profile_to_plant(profile_type, plant_id, profile_id):
    """Keep the denormalized plant.<type>ProfileId field in sync with stored profiles."""
    from . import registry

    field_name = PROFILE_PLANT_FIELDS[profile_type]
    plant = registry.get_plant(plant_id)
    if plant and plant.get(field_name) != profile_id:
        registry.update_plant(plant_id, {field_name: profile_id})


# ---------------------------------------------------------------------------
# CLI handler
# ---------------------------------------------------------------------------

def cli_profiles(args):
    as_json = getattr(args, "json", False)
    subcmd = args.subcmd

    if subcmd == "list":
        profiles = list_profiles(args.type, plant_id=getattr(args, "plant", None))
        if as_json:
            print(json.dumps(profiles, indent=2, ensure_ascii=False))
        else:
            if not profiles:
                print(f"No {args.type} profiles found.")
                return
            for p in profiles:
                print(f"  {p['plantId']:<12} {p.get('displayName', '?')}")
            print(f"\n{len(profiles)} profile(s)")

    elif subcmd == "get":
        profile = get_profile(args.type, args.plantId)
        if profile:
            print(json.dumps(profile, indent=2, ensure_ascii=False))
        else:
            print(f"No {args.type} profile found for {args.plantId}")

    elif subcmd == "set":
        profile_data = json.loads(args.data)
        result = set_profile(args.type, args.plantId, profile_data)
        if as_json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"Set {args.type} profile for {args.plantId}")

    elif subcmd == "remove":
        removed = remove_profile(args.type, args.plantId)
        if removed:
            print(f"Removed {args.type} profile for {args.plantId}")
        else:
            print(f"No {args.type} profile found for {args.plantId}")

    else:
        print("Usage: plant_mgmt profiles {list|get|set|remove}")
