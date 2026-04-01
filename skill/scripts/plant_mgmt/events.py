"""Event logging and querying for care history."""

import json
import uuid
from datetime import datetime, timezone

from . import store
from . import registry


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _generate_event_id():
    return f"evt_{uuid.uuid4()}"


def _sync_repotting_profile(event):
    """Keep repotting profile anchors aligned with confirmation history."""
    if event.get("type") != "repotting_confirmed":
        return

    from . import profiles

    effective_date = event.get("effectiveDateLocal")
    for plant_id in event.get("plantIds", []):
        plant = registry.get_plant(plant_id)
        if not plant:
            continue
        profile_ref = plant.get("repottingProfileId") or plant_id
        profile = profiles.get_profile("repotting", profile_ref)
        if not profile:
            continue
        updated_profile = dict(profile)
        updated_profile["lastRepottedAt"] = effective_date
        profiles.set_profile("repotting", plant_id, updated_profile)


def log_event(*, event_type, source="system", plant_id=None, plant_ids=None,
              location_id=None, scope=None, effective_date=None,
              effective_precision="day", effective_part_of_day=None,
              details=None):
    """Log a new care event.

    Args:
        event_type: Event type string (e.g. "watering_confirmed", "neem_confirmed").
        source: How this event was recorded ("user_free_text", "agent_inference", "system").
        plant_id: Single plant ID (convenience — added to plant_ids).
        plant_ids: List of affected plant IDs.
        location_id: Associated location ID.
        scope: Scope description string.
        effective_date: YYYY-MM-DD when the event actually happened.
        effective_precision: "day", "part_of_day", "hour", or "exact".
        effective_part_of_day: "morning", "afternoon", "evening", or "night".
        details: Dict with event-type-specific details.

    Returns:
        The created event dict.
    """
    if plant_ids is None:
        plant_ids = []
    if plant_id and plant_id not in plant_ids:
        plant_ids.append(plant_id)
    plant_ids = list(dict.fromkeys(plant_ids))

    for target_plant_id in plant_ids:
        if not registry.get_plant(target_plant_id):
            raise ValueError(f"Plant not found: {target_plant_id}")
    if location_id and not registry.get_location(location_id):
        raise ValueError(f"Location not found: {location_id}")

    event = {
        "eventId": _generate_event_id(),
        "timestamp": _now_iso(),
        "type": event_type,
        "source": source,
        "effectiveDateLocal": effective_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "effectivePrecision": effective_precision,
        "scope": scope,
        "locationId": location_id,
        "plantIds": plant_ids,
        "details": details or {},
    }

    if effective_part_of_day:
        event["effectivePartOfDay"] = effective_part_of_day

    data = store.read("events.json")
    data["events"].append(event)
    store.write("events.json", data)
    _sync_repotting_profile(event)
    return event


def list_events(*, plant_id=None, event_type=None, since=None, limit=20):
    """List events with optional filters.

    Args:
        plant_id: Filter by plant ID (checks plantIds array).
        event_type: Filter by event type.
        since: Filter events since this date (YYYY-MM-DD).
        limit: Maximum events to return.

    Returns:
        List of events, newest first.
    """
    data = store.read("events.json")
    events = data["events"]

    if plant_id:
        events = [e for e in events if plant_id in e.get("plantIds", [])]
    if event_type:
        events = [e for e in events if e["type"] == event_type]
    if since:
        events = [e for e in events if (e.get("effectiveDateLocal") or "") >= since]

    # Sort newest first
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    if limit:
        events = events[:limit]

    return events


def get_last_event(plant_id, *, event_type=None):
    """Get the most recent event for a plant, optionally filtered by type."""
    events = list_events(plant_id=plant_id, event_type=event_type, limit=1)
    return events[0] if events else None


def get_last_event_by_type(plant_id, event_types):
    """Get the most recent event for a plant matching any of the given types."""
    data = store.read("events.json")
    matching = [
        e for e in data["events"]
        if plant_id in e.get("plantIds", []) and e["type"] in event_types
    ]
    if not matching:
        return None
    matching.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return matching[0]


# ---------------------------------------------------------------------------
# CLI handler
# ---------------------------------------------------------------------------

def cli_events(args):
    as_json = getattr(args, "json", False)
    subcmd = args.subcmd

    if subcmd == "log":
        plant_ids = []
        if getattr(args, "plant", None):
            plant_ids.append(args.plant)
        if getattr(args, "plants", None):
            plant_ids.extend(args.plants.split(","))

        details = None
        if getattr(args, "details", None):
            details = json.loads(args.details)

        event = log_event(
            event_type=args.type,
            plant_ids=plant_ids or None,
            location_id=getattr(args, "location", None),
            scope=getattr(args, "scope", None),
            details=details,
        )
        if as_json:
            print(json.dumps(event, indent=2, ensure_ascii=False))
        else:
            print(f"Logged: {event['eventId']} ({event['type']})")

    elif subcmd == "list":
        events = list_events(
            plant_id=getattr(args, "plant", None),
            event_type=getattr(args, "type", None),
            since=getattr(args, "since", None),
            limit=getattr(args, "limit", 20),
        )
        if as_json:
            print(json.dumps(events, indent=2, ensure_ascii=False))
        else:
            if not events:
                print("No events found.")
                return
            for e in events:
                date = e.get("effectiveDateLocal", "?")
                plants = ", ".join(e.get("plantIds", []))[:40]
                print(f"  {date}  {e['type']:<25} {plants}")
            print(f"\n{len(events)} event(s)")

    elif subcmd == "last":
        event = get_last_event(
            args.plantId,
            event_type=getattr(args, "type", None),
        )
        if event:
            print(json.dumps(event, indent=2, ensure_ascii=False))
        else:
            print(f"No events found for {args.plantId}")

    else:
        print("Usage: plant_mgmt events {log|list|last}")
