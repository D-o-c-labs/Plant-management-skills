"""Event logging and querying for care history."""

import json
import uuid
from datetime import date, datetime, timezone

from . import config
from . import registry
from . import store


PART_OF_DAY_HOURS = {
    "morning": 9,
    "afternoon": 15,
    "evening": 19,
    "night": 22,
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _generate_event_id():
    return f"evt_{uuid.uuid4()}"


def _get_timezone(tz_name=None):
    resolved_name = tz_name
    if not resolved_name:
        try:
            resolved_name = config.load_config().get("timezone", "UTC")
        except Exception:
            resolved_name = "UTC"

    try:
        import zoneinfo

        return zoneinfo.ZoneInfo(resolved_name)
    except (ImportError, KeyError):
        return timezone.utc


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _parse_effective_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _normalize_effective_fields(
    *,
    effective_date=None,
    effective_datetime=None,
    effective_precision="day",
    effective_part_of_day=None,
):
    """Validate and normalize effective-time fields before writing an event."""
    allowed_precisions = {"day", "part_of_day", "hour", "exact"}
    if effective_precision not in allowed_precisions:
        raise ValueError(
            f"Invalid effective precision: {effective_precision}. "
            "Expected one of day, part_of_day, hour, exact."
        )

    parsed_effective_datetime = _parse_iso(effective_datetime)
    if effective_datetime and parsed_effective_datetime is None:
        raise ValueError("effective_datetime must be a valid ISO 8601 datetime string")

    parsed_effective_date = _parse_effective_date(effective_date)
    if effective_date and parsed_effective_date is None:
        raise ValueError("effective_date must be YYYY-MM-DD")

    if parsed_effective_datetime and parsed_effective_date:
        if parsed_effective_datetime.date() != parsed_effective_date:
            raise ValueError(
                "effective_date must match the calendar date of effective_datetime"
            )

    if effective_precision in {"hour", "exact"}:
        if effective_part_of_day is not None:
            raise ValueError(
                "effective_part_of_day is only valid when effective_precision is part_of_day"
            )
        if parsed_effective_datetime is None:
            raise ValueError(
                "effective_datetime is required when effective_precision is hour or exact"
            )
        parsed_effective_date = parsed_effective_datetime.date()
    elif effective_precision == "part_of_day":
        if effective_part_of_day not in PART_OF_DAY_HOURS:
            raise ValueError(
                "effective_part_of_day must be one of morning, afternoon, evening, night"
            )
        if parsed_effective_datetime is not None:
            raise ValueError(
                "effective_datetime is only supported when effective_precision is hour or exact"
            )
        if parsed_effective_date is None:
            raise ValueError(
                "effective_date is required when effective_precision is part_of_day"
            )
    else:
        if effective_part_of_day is not None:
            raise ValueError(
                "effective_part_of_day is only valid when effective_precision is part_of_day"
            )
        if parsed_effective_datetime is not None:
            raise ValueError(
                "effective_datetime is only supported when effective_precision is hour or exact"
            )
        if parsed_effective_date is None:
            parsed_effective_date = datetime.now(timezone.utc).date()

    return {
        "effective_date": parsed_effective_date.isoformat() if parsed_effective_date else None,
        "effective_datetime": parsed_effective_datetime.isoformat()
        if parsed_effective_datetime
        else None,
        "effective_precision": effective_precision,
        "effective_part_of_day": effective_part_of_day,
    }


def get_event_anchor_datetime(event, *, tz_name=None):
    """Resolve the effective scheduling anchor for an event."""
    tz = _get_timezone(tz_name)
    precision = event.get("effectivePrecision") or "day"
    effective_datetime = _parse_iso(event.get("effectiveDateTimeLocal"))
    if effective_datetime is not None:
        if effective_datetime.tzinfo is None:
            return effective_datetime.replace(tzinfo=tz)
        return effective_datetime

    effective_date = _parse_effective_date(event.get("effectiveDateLocal"))
    if effective_date is not None:
        anchor_hour = 12
        if precision == "part_of_day":
            anchor_hour = PART_OF_DAY_HOURS.get(event.get("effectivePartOfDay"), 12)
        return datetime(
            effective_date.year,
            effective_date.month,
            effective_date.day,
            anchor_hour,
            tzinfo=tz,
        )

    timestamp = _parse_iso(event.get("timestamp"))
    if timestamp is not None and timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def get_event_sort_key(event, *, tz_name=None):
    anchor_dt = get_event_anchor_datetime(event, tz_name=tz_name)
    if anchor_dt is None:
        anchor_dt = datetime.min.replace(tzinfo=timezone.utc)

    timestamp = _parse_iso(event.get("timestamp")) or anchor_dt
    if anchor_dt.tzinfo is None:
        anchor_dt = anchor_dt.replace(tzinfo=timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return anchor_dt.astimezone(timezone.utc), timestamp.astimezone(timezone.utc)


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


def log_event(
    *,
    event_type,
    source="system",
    plant_id=None,
    plant_ids=None,
    location_id=None,
    scope=None,
    effective_date=None,
    effective_datetime=None,
    effective_precision="day",
    effective_part_of_day=None,
    details=None,
):
    """Log a new care event.

    Args:
        event_type: Event type string (e.g. "watering_confirmed", "neem_confirmed").
        source: How this event was recorded ("user_free_text", "agent_inference", "system").
        plant_id: Single plant ID (convenience — added to plant_ids).
        plant_ids: List of affected plant IDs.
        location_id: Associated location ID.
        scope: Scope description string.
        effective_date: YYYY-MM-DD when the event actually happened.
        effective_datetime: ISO 8601 local datetime when the event actually happened.
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

    effective_fields = _normalize_effective_fields(
        effective_date=effective_date,
        effective_datetime=effective_datetime,
        effective_precision=effective_precision,
        effective_part_of_day=effective_part_of_day,
    )

    event = {
        "eventId": _generate_event_id(),
        "timestamp": _now_iso(),
        "type": event_type,
        "source": source,
        "effectiveDateLocal": effective_fields["effective_date"],
        "effectiveDateTimeLocal": effective_fields["effective_datetime"],
        "effectivePrecision": effective_fields["effective_precision"],
        "scope": scope,
        "locationId": location_id,
        "plantIds": plant_ids,
        "details": details or {},
    }

    if effective_fields["effective_part_of_day"]:
        event["effectivePartOfDay"] = effective_fields["effective_part_of_day"]

    data = store.read("events.json")
    data["events"].append(event)
    store.write("events.json", data)
    _sync_repotting_profile(event)
    return event


def list_events(*, plant_id=None, event_type=None, since=None, limit=20, tz_name=None):
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

    # Sort newest first using effective event time when available.
    events.sort(key=lambda e: get_event_sort_key(e, tz_name=tz_name), reverse=True)

    if limit:
        events = events[:limit]

    return events


def get_last_event(plant_id, *, event_type=None, tz_name=None):
    """Get the most recent event for a plant, optionally filtered by type."""
    events = list_events(
        plant_id=plant_id,
        event_type=event_type,
        limit=1,
        tz_name=tz_name,
    )
    return events[0] if events else None


def get_last_event_by_type(plant_id, event_types, *, tz_name=None):
    """Get the most recent event for a plant matching any of the given types."""
    data = store.read("events.json")
    matching = [
        e for e in data["events"]
        if plant_id in e.get("plantIds", []) and e["type"] in event_types
    ]
    if not matching:
        return None
    matching.sort(key=lambda e: get_event_sort_key(e, tz_name=tz_name), reverse=True)
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
            effective_date=getattr(args, "effective_date", None),
            effective_datetime=getattr(args, "effective_datetime", None),
            effective_precision=getattr(args, "effective_precision", "day"),
            effective_part_of_day=getattr(args, "effective_part_of_day", None),
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
