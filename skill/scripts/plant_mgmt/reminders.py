"""Reminder state management: CRUD on reminder tasks, status transitions, confirmations."""

import json
from datetime import datetime, timezone

from . import schemas
from . import store
from . import events as events_mod

TASK_CONFIRM_EVENT_TYPES = {
    "watering_check": "watering_confirmed",
    "fertilization_check": "fertilization_confirmed",
    "repotting_check": "repotting_confirmed",
    "healthcheck_check": "healthcheck_confirmed",
    "maintenance_check": "maintenance_confirmed",
    "pruning_check": "pruning_confirmed",
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _target_state_version():
    schema = schemas.get_schema_for_file("reminder_state.json") or {}
    return (
        schema.get("properties", {})
        .get("version", {})
        .get("const", 2)
    )


def _find_neem_program(plant_id):
    """Return the unique neem recurring program for a plant, if one exists."""
    from . import profiles

    profile = profiles.get_profile("pest", plant_id)
    if not profile:
        return None

    matches = [
        program
        for program in profile.get("recurringPrograms", [])
        if program.get("confirmEventType") == "neem_confirmed"
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def normalize_state_payload(data):
    """Normalize reminder state payloads before validation/write."""
    if not isinstance(data, dict):
        raise ValueError("reminder_state.json root must be a JSON object")

    changed = False
    repairs = []
    warnings = []
    normalized = dict(data)

    target_version = _target_state_version()
    if normalized.get("version") != target_version:
        normalized["version"] = target_version
        changed = True
        repairs.append(f"set version to {target_version}")

    tasks = normalized.get("tasks")
    if not isinstance(tasks, dict):
        normalized["tasks"] = {}
        tasks = normalized["tasks"]
        changed = True
        repairs.append("reset tasks to an empty object")

    meta = normalized.get("meta")
    if not isinstance(meta, dict):
        normalized["meta"] = {}
        changed = True
        repairs.append("reset meta to an empty object")

    normalized_tasks = {}
    for original_key, raw_task in tasks.items():
        if not isinstance(raw_task, dict):
            changed = True
            warnings.append(f"dropped non-object task entry at key {original_key}")
            continue

        task = dict(raw_task)
        task.setdefault("taskId", original_key)
        task_id = task["taskId"]
        target_key = task_id

        if task.get("type") == "neem":
            changed = True
            program = _find_neem_program(task.get("plantId"))
            if program:
                target_key = (
                    f"{program.get('taskType') or 'pest_program'}:"
                    f"pest_recurring_programs:{task.get('plantId')}:{program.get('programId')}"
                )
                task["taskId"] = target_key
                task["type"] = program.get("taskType") or "pest_program"
                task["managedByRuleId"] = "pest_recurring_programs"
                task["programId"] = program.get("programId")
                task["confirmEventType"] = program.get("confirmEventType") or "neem_confirmed"
                repairs.append(f"converted legacy neem task {original_key} to {target_key}")
            elif task.get("status") == "open":
                task["status"] = "expired"
                task["lastEvaluationAt"] = _now_iso()
                task["lastReason"] = (
                    "Expired during repair: standalone neem tasks are no longer supported. "
                    "Re-run eval to regenerate pest recurring-program tasks."
                )
                repairs.append(f"expired unsupported legacy neem task {original_key}")
            else:
                warnings.append(
                    f"left historical standalone neem task {original_key} unchanged because no unique pest program matched"
                )

        if target_key in normalized_tasks and target_key != original_key:
            repairs.append(
                f"dropped superseded legacy task {original_key} because {target_key} already exists"
            )
            changed = True
            continue

        if target_key != original_key:
            changed = True
        normalized_tasks[target_key] = task

    if normalized_tasks != tasks:
        normalized["tasks"] = normalized_tasks
        changed = True

    return normalized, changed, repairs, warnings


def repair_state():
    """Repair reminder_state.json in place when recoverable."""
    raw_data = store.read("reminder_state.json", validate=False)
    normalized, changed, repairs, warnings = normalize_state_payload(raw_data)

    if changed:
        store.write("reminder_state.json", normalized)

    return {
        "changed": changed,
        "repairsApplied": repairs,
        "warnings": warnings,
        "versionBefore": raw_data.get("version") if isinstance(raw_data, dict) else None,
        "versionAfter": normalized.get("version"),
    }


def list_tasks(*, status=None):
    """List reminder tasks, optionally filtered by status."""
    data = store.read("reminder_state.json")
    tasks = list(data["tasks"].values())
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    # Sort by dueAt or createdAt
    tasks.sort(key=lambda t: t.get("dueAt") or t.get("createdAt", ""))
    return tasks


def get_task(task_id):
    """Get a single reminder task by ID."""
    data = store.read("reminder_state.json")
    return data["tasks"].get(task_id)


def open_task(*, task_id, task_type, plant_id=None, location_id=None,
              sublocation_id=None, reason=None, due_at=None,
              managed_by_rule_id=None, program_id=None,
              confirm_event_type=None):
    """Open a new reminder task (or update existing if same ID)."""
    data = store.read("reminder_state.json")

    now = _now_iso()
    existing = data["tasks"].get(task_id)

    if existing and existing["status"] == "open":
        # Update existing open task
        existing["lastEvaluationAt"] = now
        existing["lastReason"] = reason or existing.get("lastReason")
        if due_at:
            existing["dueAt"] = due_at
        if managed_by_rule_id is not None:
            existing["managedByRuleId"] = managed_by_rule_id
        if program_id is not None:
            existing["programId"] = program_id
        if confirm_event_type is not None:
            existing["confirmEventType"] = confirm_event_type
        data["tasks"][task_id] = existing
    else:
        # Create new task
        data["tasks"][task_id] = {
            "taskId": task_id,
            "type": task_type,
            "status": "open",
            "plantId": plant_id,
            "locationId": location_id,
            "subLocationId": sublocation_id,
            "createdAt": now,
            "dueAt": due_at or now,
            "lastReminderAt": None,
            "lastEvaluationAt": now,
            "lastReason": reason,
            "pushCount": 0,
            "confirmationEventId": None,
            "managedByRuleId": managed_by_rule_id,
            "programId": program_id,
            "confirmEventType": confirm_event_type,
        }

    store.write("reminder_state.json", data)
    return data["tasks"][task_id]


def mark_reminded(task_id):
    """Record that a reminder was sent for this task."""
    data = store.read("reminder_state.json")
    task = data["tasks"].get(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")

    task["lastReminderAt"] = _now_iso()
    task["pushCount"] = task.get("pushCount", 0) + 1
    data["tasks"][task_id] = task
    store.write("reminder_state.json", data)
    return task


def confirm_task(
    task_id,
    *,
    details=None,
    effective_date=None,
    effective_datetime=None,
    effective_precision="day",
    effective_part_of_day=None,
):
    """Confirm/close a reminder task and log a confirmation event.

    Returns (task, event) tuple.
    """
    data = store.read("reminder_state.json")
    task = data["tasks"].get(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")
    if task["status"] != "open":
        raise ValueError(f"Only open tasks can be confirmed: {task_id}")
    if task.get("type") == "neem" and not task.get("confirmEventType"):
        raise ValueError(
            "Standalone neem reminder tasks are no longer supported. Run `reminders repair` first."
        )

    # Log confirmation event
    event_type = (
        task.get("confirmEventType")
        or TASK_CONFIRM_EVENT_TYPES.get(task["type"], f"{task['type']}_confirmed")
    )
    event = events_mod.log_event(
        event_type=event_type,
        source="user_free_text",
        plant_id=task.get("plantId"),
        location_id=task.get("locationId"),
        scope=f"task:{task_id}",
        effective_date=effective_date,
        effective_datetime=effective_datetime,
        effective_precision=effective_precision,
        effective_part_of_day=effective_part_of_day,
        details={"taskId": task_id, "userDetails": details},
    )

    # Re-read in case events.log_event didn't touch reminder_state
    data = store.read("reminder_state.json")
    task = data["tasks"][task_id]
    task["status"] = "done"
    task["confirmationEventId"] = event["eventId"]
    task["lastEvaluationAt"] = _now_iso()
    task["lastReason"] = f"Confirmed: {details}" if details else "Confirmed"
    data["tasks"][task_id] = task
    store.write("reminder_state.json", data)

    return task, event


def cancel_task(task_id, *, reason=None):
    """Cancel a reminder task."""
    data = store.read("reminder_state.json")
    task = data["tasks"].get(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")

    task["status"] = "cancelled"
    task["lastEvaluationAt"] = _now_iso()
    task["lastReason"] = f"Cancelled: {reason}" if reason else "Cancelled"
    data["tasks"][task_id] = task
    store.write("reminder_state.json", data)
    return task


def expire_task(task_id, *, reason=None):
    """Expire a reminder task (no longer relevant)."""
    data = store.read("reminder_state.json")
    task = data["tasks"].get(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")

    task["status"] = "expired"
    task["lastEvaluationAt"] = _now_iso()
    task["lastReason"] = reason or "Expired"
    data["tasks"][task_id] = task
    store.write("reminder_state.json", data)
    return task


def reset_stale_tasks(*, max_age_days=30):
    """Clean up old done/expired/cancelled tasks beyond max_age_days.

    Returns count of tasks cleaned up.
    """
    data = store.read("reminder_state.json")
    now = datetime.now(timezone.utc)
    to_remove = []

    for task_id, task in data["tasks"].items():
        if task["status"] in ("done", "expired", "cancelled"):
            created = task.get("createdAt", "")
            try:
                created_dt = datetime.fromisoformat(created)
                if (now - created_dt).days > max_age_days:
                    to_remove.append(task_id)
            except (ValueError, TypeError):
                pass

    for task_id in to_remove:
        del data["tasks"][task_id]

    if to_remove:
        store.write("reminder_state.json", data)

    return len(to_remove)


# ---------------------------------------------------------------------------
# CLI handler
# ---------------------------------------------------------------------------

def cli_reminders(args):
    as_json = getattr(args, "json", False)
    subcmd = args.subcmd

    if subcmd == "list":
        tasks = list_tasks(status=getattr(args, "status", None))
        if as_json:
            print(json.dumps(tasks, indent=2, ensure_ascii=False))
        else:
            if not tasks:
                print("No reminder tasks found.")
                return
            for t in tasks:
                plant = t.get("plantId") or t.get("locationId") or "?"
                pushes = t.get("pushCount", 0)
                print(f"  [{t['status']:<9}] {t['taskId']:<40} {plant:<15} pushes={pushes}")
            print(f"\n{len(tasks)} task(s)")

    elif subcmd == "get":
        task = get_task(args.taskId)
        if task:
            print(json.dumps(task, indent=2, ensure_ascii=False))
        else:
            print(f"Task not found: {args.taskId}")

    elif subcmd == "confirm":
        task, event = confirm_task(
            args.taskId,
            details=getattr(args, "details", None),
            effective_date=getattr(args, "effective_date", None),
            effective_datetime=getattr(args, "effective_datetime", None),
            effective_precision=getattr(args, "effective_precision", "day"),
            effective_part_of_day=getattr(args, "effective_part_of_day", None),
        )
        if as_json:
            print(json.dumps({"task": task, "event": event}, indent=2, ensure_ascii=False))
        else:
            print(f"Confirmed: {task['taskId']} → event {event['eventId']}")

    elif subcmd == "cancel":
        task = cancel_task(
            args.taskId,
            reason=getattr(args, "reason", None),
        )
        print(f"Cancelled: {task['taskId']}")

    elif subcmd == "reset":
        count = reset_stale_tasks()
        print(f"Cleaned up {count} stale task(s).")

    elif subcmd == "repair":
        result = repair_state()
        if as_json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            status = "changed" if result["changed"] else "no changes"
            print(f"Reminder state repair: {status}")
            if result["repairsApplied"]:
                print("Repairs applied:")
                for item in result["repairsApplied"]:
                    print(f"  - {item}")
            if result["warnings"]:
                print("Warnings:")
                for item in result["warnings"]:
                    print(f"  - {item}")

    else:
        print("Usage: plant_mgmt reminders {list|get|confirm|cancel|reset|repair}")
