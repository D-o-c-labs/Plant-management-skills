"""Reminder state management: CRUD on reminder tasks, status transitions, confirmations."""

import json
from datetime import datetime, timezone

from . import store
from . import events as events_mod

TASK_CONFIRM_EVENT_TYPES = {
    "watering_check": "watering_confirmed",
    "fertilization_check": "fertilization_confirmed",
    "neem": "neem_confirmed",
    "repotting_check": "repotting_confirmed",
    "healthcheck_check": "healthcheck_confirmed",
    "maintenance_check": "maintenance_confirmed",
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


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
              sublocation_id=None, reason=None, due_at=None):
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


def confirm_task(task_id, *, details=None):
    """Confirm/close a reminder task and log a confirmation event.

    Returns (task, event) tuple.
    """
    data = store.read("reminder_state.json")
    task = data["tasks"].get(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")

    # Log confirmation event
    event_type = TASK_CONFIRM_EVENT_TYPES.get(task["type"], f"{task['type']}_confirmed")
    event = events_mod.log_event(
        event_type=event_type,
        source="user_free_text",
        plant_id=task.get("plantId"),
        location_id=task.get("locationId"),
        scope=f"task:{task_id}",
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

    else:
        print("Usage: plant_mgmt reminders {list|get|confirm|cancel|reset}")
