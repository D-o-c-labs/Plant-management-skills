"""Deterministic care evaluation engine.

Reads all data files, determines what care actions are due, and outputs
structured JSON for an AI agent to interpret and communicate.
"""

import json
from datetime import datetime, timezone, timedelta

from . import config, events, profiles, registry, reminders

from . import store


# ---------------------------------------------------------------------------
# Season helpers
# ---------------------------------------------------------------------------

SEASON_MAP = {
    1: "winter", 2: "winter", 3: "spring", 4: "spring",
    5: "spring", 6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn", 12: "winter",
}


def get_season(month: int) -> str:
    return SEASON_MAP.get(month, "unknown")


def get_current_context(weather=None, tz_name=None):
    """Build the evaluation context dict."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name) if tz_name else timezone.utc
    except (ImportError, KeyError):
        tz = timezone.utc

    now = datetime.now(tz)
    return {
        "evaluatedAt": now.isoformat(),
        "season": get_season(now.month),
        "month": now.month,
        "dayOfWeek": now.strftime("%A").lower(),
        "timeLocal": now.strftime("%H:%M"),
        "hour": now.hour,
        "isWeekend": now.weekday() >= 5,
        "weatherProvided": weather is not None,
        "weather": weather,
    }


# ---------------------------------------------------------------------------
# Interval / due checks
# ---------------------------------------------------------------------------

def _parse_iso(s):
    """Parse an ISO timestamp string, return datetime or None."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _days_since(iso_str):
    """Days since an ISO timestamp. Returns None if unparseable."""
    dt = _parse_iso(iso_str)
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 86400


def _get_baseline_interval(profile, season):
    """Extract [min, max] baseline interval days from a watering profile for the current season."""
    baseline = profile.get("seasonalBaseline", {}).get(season)
    if baseline:
        return baseline.get("baseIntervalDays", [7, 14])
    return [7, 14]  # fallback


def _determine_urgency(days_since, interval_min, interval_max):
    """Determine urgency based on how far past the interval we are."""
    if days_since is None:
        return "medium", "No event history — check recommended"

    if days_since < interval_min:
        return None, None  # not due yet

    if days_since <= interval_max:
        return "low", f"Within baseline window ({days_since:.0f} days, baseline {interval_min}-{interval_max})"

    overshoot = days_since - interval_max
    if overshoot <= interval_max * 0.5:
        return "medium", f"Past baseline ({days_since:.0f} days, baseline {interval_min}-{interval_max})"

    if overshoot <= interval_max:
        return "high", f"Significantly overdue ({days_since:.0f} days, baseline {interval_min}-{interval_max})"

    return "critical", f"Very overdue ({days_since:.0f} days, baseline {interval_min}-{interval_max})"


# ---------------------------------------------------------------------------
# Push policy
# ---------------------------------------------------------------------------

def _should_push(task, ctx, push_config):
    """Check if we should send a reminder for this task based on push policy."""
    last_reminder = _parse_iso(task.get("lastReminderAt"))
    if not last_reminder:
        return True  # never reminded

    now = datetime.now(timezone.utc)
    if last_reminder.tzinfo is None:
        last_reminder = last_reminder.replace(tzinfo=timezone.utc)
    hours_since = (now - last_reminder).total_seconds() / 3600

    is_weekend = ctx.get("isWeekend", False)
    hour = ctx.get("hour", 12)

    day_key = "weekend" if is_weekend else "weekday"
    day_policy = push_config.get(day_key, {})
    active_hours = day_policy.get("activeHours", [7, 23])

    if hour < active_hours[0] or hour >= active_hours[1]:
        return False  # outside active hours

    min_hours = day_policy.get("minHoursBetweenPushes", 2)
    if isinstance(min_hours, dict):
        # Time-range based policy
        for time_range, hours_val in min_hours.items():
            parts = time_range.split("-")
            if len(parts) == 2:
                start_h = int(parts[0][:2])
                end_h = int(parts[1][:2])
                if start_h <= hour < end_h:
                    min_hours = hours_val
                    break
        else:
            min_hours = 2  # default if no range matched

    return hours_since >= min_hours


# ---------------------------------------------------------------------------
# Rule evaluators
# ---------------------------------------------------------------------------

def _eval_watering_checks(plants_data, care_rule, ctx, cfg):
    """Evaluate the balcony watering/check rule."""
    actions = []
    no_action = []
    season = ctx["season"]
    month = ctx["month"]

    scope_locations = care_rule.get("scope", {}).get("locationIds", [])

    for plant in plants_data:
        if plant["status"] not in ("active", "recovering"):
            continue
        if scope_locations and plant["locationId"] not in scope_locations:
            continue

        # Get watering profile
        profile_ref = plant.get("wateringProfileId") or plant["plantId"]
        profile = profiles.get_profile("watering", profile_ref)
        if not profile:
            continue

        interval = _get_baseline_interval(profile, season)

        # Find last watering-related event
        watering_types = ["watering_confirmed", "rain_confirmed"]
        last_evt = events.get_last_event_by_type(plant["plantId"], watering_types)
        last_ts = last_evt.get("timestamp") if last_evt else None
        days = _days_since(last_ts)

        urgency, reason = _determine_urgency(days, interval[0], interval[1])

        if urgency is None:
            no_action.append({
                "plantId": plant["plantId"],
                "displayName": plant["displayName"],
                "reason": f"Within baseline interval ({days:.0f} days, baseline {interval[0]}-{interval[1]})" if days is not None else "Recently checked",
            })
            continue

        # Adjust for recovering plants
        suggested_action = "water_if_dry"
        if plant["status"] == "recovering":
            suggested_action = "check_soil_first"
            if urgency == "low":
                urgency = "medium"  # bias toward checking for recovering plants

        actions.append({
            "type": "watering_check",
            "plantId": plant["plantId"],
            "displayName": plant["displayName"],
            "locationId": plant["locationId"],
            "subLocationId": plant.get("subLocationId"),
            "urgency": urgency,
            "confidence": "high" if ctx["weatherProvided"] else "medium",
            "reason": reason,
            "daysSinceLastEvent": round(days, 1) if days is not None else None,
            "baselineInterval": interval,
            "riskFlags": plant.get("riskFlags", []),
            "irrigationEffectiveState": plant.get("irrigationEffectiveState"),
            "suggestedAction": suggested_action,
        })

    return actions, no_action


def _eval_neem_rule(plants_data, care_rule, ctx, cfg):
    """Evaluate the neem oil reminder rule."""
    actions = []
    no_action = []
    month = ctx["month"]

    season_policy = care_rule.get("seasonPolicy", {})
    disabled_months = season_policy.get("disabledMonths", [])
    reduced_months = season_policy.get("reducedMonths", [])

    if month in disabled_months:
        return actions, no_action  # fully disabled this month

    scope = care_rule.get("scope", {})
    location_id = scope.get("locationId")
    location_ids = scope.get("locationIds", [])
    if location_id and location_id not in location_ids:
        location_ids.append(location_id)
    required_flags = scope.get("requiredRiskFlagsAny", [])
    cadence = care_rule.get("cadence", {})
    target_days = cadence.get("targetDays", 12)
    max_days = cadence.get("maximumDays", 15)

    for plant in plants_data:
        if plant["status"] not in ("active", "recovering"):
            continue
        if location_ids and plant["locationId"] not in location_ids:
            continue
        if required_flags:
            plant_flags = plant.get("riskFlags", [])
            if not any(f in plant_flags for f in required_flags):
                continue

        last_evt = events.get_last_event_by_type(plant["plantId"], ["neem_confirmed"])
        last_ts = last_evt.get("timestamp") if last_evt else None
        days = _days_since(last_ts)

        if days is not None and days < target_days:
            no_action.append({
                "plantId": plant["plantId"],
                "displayName": plant["displayName"],
                "reason": f"Neem applied {days:.0f} days ago (target: {target_days}d)",
            })
            continue

        urgency = "low" if month in reduced_months else "medium"
        if days is not None and days > max_days:
            urgency = "high"

        actions.append({
            "type": "neem",
            "plantId": plant["plantId"],
            "displayName": plant["displayName"],
            "locationId": plant["locationId"],
            "subLocationId": plant.get("subLocationId"),
            "urgency": urgency,
            "confidence": "high",
            "reason": f"Neem due ({days:.0f} days since last, target {target_days}d)" if days is not None else "No neem history — initial application recommended",
            "daysSinceLastEvent": round(days, 1) if days is not None else None,
            "baselineInterval": [target_days, max_days],
            "riskFlags": plant.get("riskFlags", []),
            "suggestedAction": "apply_neem_oil",
        })

    return actions, no_action


def _eval_fertilization_rule(plants_data, care_rule, ctx, cfg):
    """Evaluate the fertilization alert rule."""
    actions = []
    no_action = []
    month = ctx["month"]

    scope_plant_ids = care_rule.get("scope", {}).get("plantIds", [])

    for plant in plants_data:
        if plant["status"] not in ("active", "recovering"):
            continue
        if scope_plant_ids and plant["plantId"] not in scope_plant_ids:
            continue

        fert_profile = profiles.get_profile("fertilization", plant.get("fertilizationProfileId") or plant["plantId"])
        if not fert_profile:
            continue

        active_months = fert_profile.get("activeMonths", [])
        if month not in active_months:
            no_action.append({
                "plantId": plant["plantId"],
                "displayName": plant["displayName"],
                "reason": f"Fertilization not active in month {month}",
            })
            continue

        interval = fert_profile.get("cadenceDays") or fert_profile.get("intervalDays") or [25, 35]

        last_evt = events.get_last_event_by_type(plant["plantId"], ["fertilization_confirmed"])
        last_ts = last_evt.get("timestamp") if last_evt else None
        days = _days_since(last_ts)

        urgency, reason = _determine_urgency(days, interval[0], interval[1])
        if urgency is None:
            no_action.append({
                "plantId": plant["plantId"],
                "displayName": plant["displayName"],
                "reason": f"Fertilization within interval ({days:.0f} days, baseline {interval[0]}-{interval[1]})" if days is not None else "Recently fertilized",
            })
            continue

        actions.append({
            "type": "fertilization_check",
            "plantId": plant["plantId"],
            "displayName": plant["displayName"],
            "locationId": plant["locationId"],
            "subLocationId": plant.get("subLocationId"),
            "urgency": urgency,
            "confidence": "high",
            "reason": reason or (f"Fertilization due ({days:.0f} days)" if days is not None else "No fertilization history"),
            "daysSinceLastEvent": round(days, 1) if days is not None else None,
            "baselineInterval": interval,
            "riskFlags": plant.get("riskFlags", []),
            "suggestedAction": "fertilize",
        })

    return actions, no_action


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

RULE_EVALUATORS = {
    "balcony_irrigation_off_seasonal_checks": _eval_watering_checks,
    "rear_balcony_aromatics_neem": _eval_neem_rule,
    "plant_fertilization_alerts": _eval_fertilization_rule,
    "watering_check": _eval_watering_checks,
    "neem": _eval_neem_rule,
    "fertilization_check": _eval_fertilization_rule,
}

MANAGED_TASK_TYPES = {"watering_check", "neem", "fertilization_check"}


def _resolve_rule_evaluator(rule):
    for key in (rule.get("evaluator"), rule.get("action"), rule.get("ruleId")):
        if key and key in RULE_EVALUATORS:
            return RULE_EVALUATORS[key]
    return None


def evaluate(*, weather=None, dry_run=False):
    """Run the full care evaluation.

    Args:
        weather: Optional weather context dict.
        dry_run: If True, don't update reminder_state.json.

    Returns:
        Structured evaluation result dict.
    """
    cfg = config.load_config()
    if cfg.get("evaluationDefaults", {}).get("weatherRequired") and weather is None:
        raise ValueError("Weather context is required by config.json for evaluation.")
    tz_name = cfg.get("timezone", "UTC")
    ctx = get_current_context(weather=weather, tz_name=tz_name)
    push_config = cfg.get("pushPolicy", {})

    plants_data = store.read("plants.json")["plants"]
    care_rules = store.read("care_rules.json")["rules"]
    open_tasks = {
        task["taskId"]: task
        for task in reminders.list_tasks(status="open")
    }

    all_actions = []
    all_no_action = []
    suppressed_actions = []
    state_changes = {"opened": [], "closed": [], "updated": []}

    for rule in care_rules:
        if not rule.get("enabled", False):
            continue

        evaluator = _resolve_rule_evaluator(rule)
        if not evaluator:
            continue

        actions, no_action = evaluator(plants_data, rule, ctx, cfg)
        all_actions.extend(actions)
        all_no_action.extend(no_action)

    due_task_ids = set()
    pushable_actions = []
    for action in all_actions:
        task_id = f"{action['type']}:{action['plantId']}"
        action = {**action, "taskId": task_id}
        due_task_ids.add(task_id)
        existing_task = open_tasks.get(task_id)

        if not dry_run:
            reminders.open_task(
                task_id=task_id,
                task_type=action["type"],
                plant_id=action.get("plantId"),
                location_id=action.get("locationId"),
                sublocation_id=action.get("subLocationId"),
                reason=action.get("reason"),
            )

        if existing_task and existing_task["status"] == "open":
            if _should_push(existing_task, ctx, push_config):
                pushable_actions.append(action)
                state_changes["updated"].append(task_id)
                if not dry_run:
                    reminders.mark_reminded(task_id)
            else:
                suppressed_actions.append({
                    **action,
                    "suppressedBy": "push_policy",
                    "lastReminderAt": existing_task.get("lastReminderAt"),
                })
        else:
            pushable_actions.append(action)
            state_changes["opened"].append(task_id)
            if not dry_run:
                reminders.mark_reminded(task_id)

    for task_id, task in open_tasks.items():
        if task.get("type") in MANAGED_TASK_TYPES and task_id not in due_task_ids:
            state_changes["closed"].append(task_id)
            if not dry_run:
                reminders.expire_task(task_id, reason="No longer due after evaluation")

    result = {
        "evaluatedAt": ctx["evaluatedAt"],
        "context": ctx,
        "actions": pushable_actions,
        "suppressedActions": suppressed_actions,
        "noAction": all_no_action,
        "stateChanges": state_changes,
        "dryRun": dry_run,
        "summary": {
            "totalActions": len(pushable_actions),
            "totalSuppressed": len(suppressed_actions),
            "totalNoAction": len(all_no_action),
            "byType": {},
        },
    }

    # Build summary by type
    for a in pushable_actions:
        t = a["type"]
        result["summary"]["byType"][t] = result["summary"]["byType"].get(t, 0) + 1

    return result


def quick_status():
    """Quick status: what is due right now without mutating reminder state."""
    snapshot = evaluate(dry_run=True)
    open_tasks = reminders.list_tasks(status="open")

    return {
        "evaluatedAt": snapshot["evaluatedAt"],
        "openTasks": len(open_tasks),
        "dueNow": snapshot["summary"]["totalActions"],
        "suppressedNow": snapshot["summary"]["totalSuppressed"],
        "tasks": snapshot["actions"],
        "openTaskState": [
            {
                "taskId": t["taskId"],
                "type": t["type"],
                "plantId": t.get("plantId"),
                "pushCount": t.get("pushCount", 0),
                "lastReason": t.get("lastReason"),
                "dueAt": t.get("dueAt"),
            }
            for t in open_tasks
        ],
    }


# ---------------------------------------------------------------------------
# CLI handler
# ---------------------------------------------------------------------------

def cli_eval(args):
    as_json = getattr(args, "json", False)
    subcmd = args.subcmd

    if subcmd == "status":
        result = quick_status()
        if as_json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"Due now: {result['dueNow']}  Open tasks: {result['openTasks']}")
            for t in result["tasks"]:
                print(f"  [{t['urgency']:<8}] {t['taskId']:<45} {t['displayName']}")
            if result["suppressedNow"]:
                print(f"Suppressed by push policy: {result['suppressedNow']}")

    elif subcmd == "run" or subcmd is None:
        weather = None
        if getattr(args, "weather", None):
            weather = json.loads(args.weather)
        dry_run = getattr(args, "dry_run", False)

        result = evaluate(weather=weather, dry_run=dry_run)

        if as_json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            dr = " (DRY RUN)" if dry_run else ""
            print(f"Evaluation{dr} at {result['evaluatedAt']}")
            print(f"Season: {result['context']['season']}, "
                  f"Weather: {'yes' if result['context']['weatherProvided'] else 'no'}")
            print(f"\nActions ({result['summary']['totalActions']}):")
            for a in result["actions"]:
                print(f"  [{a['urgency']:<8}] {a['type']:<25} {a['displayName']:<25} {a.get('reason','')[:50]}")
            if not result["actions"]:
                print("  (none)")
            print(f"\nNo action ({result['summary']['totalNoAction']}): use --json for details")

    else:
        print("Usage: plant_mgmt eval {run|status} [--weather JSON] [--dry-run] [--json]")
