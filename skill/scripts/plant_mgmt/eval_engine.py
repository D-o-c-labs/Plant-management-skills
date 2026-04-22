"""Deterministic care evaluation engine.

Reads all data files, determines what care actions are due, and outputs
structured JSON for an AI agent to interpret and communicate.
"""

import json
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from . import config, events, profiles, reminders, store


# ---------------------------------------------------------------------------
# Season helpers
# ---------------------------------------------------------------------------

SEASON_MAP = {
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
    12: "winter",
}

DEFAULT_ACTIVE_STATUSES = ["active", "recovering"]
LEGACY_MANAGED_TASK_TYPES = {"watering_check", "fertilization_check"}


def get_season(month: int) -> str:
    return SEASON_MAP.get(month, "unknown")


def get_current_context(weather=None, tz_name=None):
    """Build the evaluation context dict."""
    tz = _get_timezone(tz_name)

    now = datetime.now(tz)
    return {
        "evaluatedAt": now.isoformat(),
        "timezone": getattr(tz, "key", str(tz)),
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

def _get_timezone(tz_name):
    try:
        import zoneinfo

        return zoneinfo.ZoneInfo(tz_name) if tz_name else timezone.utc
    except (ImportError, KeyError):
        return timezone.utc

def _parse_iso(s):
    """Parse an ISO timestamp string, return datetime or None."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _parse_anchor_value(value, tz_name):
    """Parse a profile or event anchor value using the local plant timezone."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value)
        try:
            if "T" in text:
                dt = datetime.fromisoformat(text)
            else:
                parsed = date.fromisoformat(text)
                dt = datetime(parsed.year, parsed.month, parsed.day)
        except (TypeError, ValueError):
            return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=_get_timezone(tz_name))
    return dt


def _event_anchor_datetime(event, tz_name):
    """Resolve the scheduling anchor for an event."""
    return events.get_event_anchor_datetime(event, tz_name=tz_name)


def _event_sort_key(event, tz_name):
    return events.get_event_sort_key(event, tz_name=tz_name)


def _days_since(anchor_dt, reference_dt):
    """Days since a datetime anchor. Returns None if anchor is missing."""
    if not anchor_dt:
        return None
    return (reference_dt - anchor_dt).total_seconds() / 86400


def _format_interval_value(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _format_interval_label(interval, unit):
    unit_label = "year" if unit == "years" else "day"
    if len(interval) == 2 and interval[0] == interval[1]:
        return f"{_format_interval_value(interval[0])} {unit_label}"
    return (
        f"{_format_interval_value(interval[0])}-{_format_interval_value(interval[1])} "
        f"{unit_label}s"
    )


def _normalise_interval(interval, fallback):
    candidate = interval if interval is not None else fallback
    if candidate is None:
        return None
    if isinstance(candidate, (int, float)):
        return [candidate, candidate]
    if isinstance(candidate, (list, tuple)) and len(candidate) == 2:
        return [candidate[0], candidate[1]]
    if fallback is None:
        return None
    return list(fallback)


def _shift_months(dt, months):
    """Add calendar months while preserving local clock time where possible."""
    month_index = (dt.month - 1) + months
    year = dt.year + month_index // 12
    month = (month_index % 12) + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _add_interval(anchor_dt, amount, unit):
    amount = float(amount)
    if unit == "years":
        return _shift_months(anchor_dt, int(round(amount * 12)))
    return anchor_dt + timedelta(days=amount)


def _determine_urgency(anchor_dt, due_min_dt, due_max_dt, baseline_label, now_dt):
    """Determine urgency based on interval thresholds and current evaluation time."""
    days_since = _days_since(anchor_dt, now_dt)
    if anchor_dt is None:
        return "medium", "No event history — check recommended", days_since

    if now_dt < due_min_dt:
        return None, None, days_since

    if now_dt <= due_max_dt:
        return (
            "low",
            f"Within baseline window ({days_since:.0f} days since last, baseline {baseline_label})",
            days_since,
        )

    overshoot = (now_dt - due_max_dt).total_seconds() / 86400
    baseline_window_days = max((due_max_dt - due_min_dt).total_seconds() / 86400, 1)
    if overshoot <= baseline_window_days * 0.5:
        return (
            "medium",
            f"Past baseline ({days_since:.0f} days since last, baseline {baseline_label})",
            days_since,
        )

    if overshoot <= baseline_window_days:
        return (
            "high",
            f"Significantly overdue ({days_since:.0f} days since last, baseline {baseline_label})",
            days_since,
        )

    return (
        "critical",
        f"Very overdue ({days_since:.0f} days since last, baseline {baseline_label})",
        days_since,
    )


def _ensure_minimum_urgency(urgency, floor):
    order = ["low", "medium", "high", "critical"]
    if urgency is None or floor not in order:
        return urgency
    if urgency not in order:
        return floor
    return order[max(order.index(urgency), order.index(floor))]


def _first_present(mapping, keys, default=None):
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _normalise_months(months):
    if not months:
        return []
    return sorted({int(month) for month in months if 1 <= int(month) <= 12})


def _group_month_windows(months):
    months = _normalise_months(months)
    if not months:
        return []

    windows = [[months[0]]]
    for month in months[1:]:
        if month == windows[-1][-1] + 1:
            windows[-1].append(month)
        else:
            windows.append([month])

    if len(windows) > 1 and windows[0][0] == 1 and windows[-1][-1] == 12:
        windows[0] = windows[-1] + windows[0]
        windows.pop()

    return windows


def _window_start(window, current_dt):
    start_month = window[0]
    wraps = any(month < prev for prev, month in zip(window, window[1:]))
    start_year = current_dt.year
    if wraps and current_dt.month < start_month:
        start_year -= 1
    return current_dt.replace(
        year=start_year,
        month=start_month,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _active_window_bounds(months, current_dt):
    for window in _group_month_windows(months):
        if current_dt.month in window:
            start_dt = _window_start(window, current_dt)
            return window, start_dt, _shift_months(start_dt, len(window))
    return None, None, None


# ---------------------------------------------------------------------------
# Push policy
# ---------------------------------------------------------------------------

def _should_push(task, ctx, push_config):
    """Check if we should send a reminder for this task based on push policy."""
    last_reminder = _parse_iso(task.get("lastReminderAt"))
    if not last_reminder:
        return True

    now = _parse_iso(ctx["evaluatedAt"]) or datetime.now(timezone.utc)
    if last_reminder.tzinfo is None:
        last_reminder = last_reminder.replace(tzinfo=timezone.utc)
    hours_since = (now - last_reminder).total_seconds() / 3600

    is_weekend = ctx.get("isWeekend", False)
    hour = ctx.get("hour", 12)

    day_key = "weekend" if is_weekend else "weekday"
    day_policy = push_config.get(day_key, {})
    active_hours = day_policy.get("activeHours", [7, 23])

    if hour < active_hours[0] or hour >= active_hours[1]:
        return False

    min_hours = day_policy.get("minHoursBetweenPushes", 2)
    if isinstance(min_hours, dict):
        for time_range, hours_val in min_hours.items():
            parts = time_range.split("-")
            if len(parts) != 2:
                continue
            start_h = int(parts[0][:2])
            end_h = int(parts[1][:2])
            if start_h <= hour < end_h:
                min_hours = hours_val
                break
        else:
            min_hours = 2

    return hours_since >= min_hours


# ---------------------------------------------------------------------------
# Generic rule helpers
# ---------------------------------------------------------------------------

def _rule_filters(rule):
    return rule.get("filters") or rule.get("scope") or {}


def _profile_for_plant(profile_type, plant):
    profile_ref = plant.get(f"{profile_type}ProfileId") or plant["plantId"]
    return profiles.get_profile(profile_type, profile_ref)


def _event_types_from(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _task_id_for_action(action):
    parts = [action["type"], action["ruleId"], action["plantId"]]
    if action.get("programId"):
        parts.append(action["programId"])
    return ":".join(parts)


def _matching_plants(plants_data, filters):
    statuses = filters.get("statuses") or DEFAULT_ACTIVE_STATUSES
    plant_ids = set(filters.get("plantIds") or [])
    location_ids = set(filters.get("locationIds") or [])
    sublocation_ids = set(filters.get("subLocationIds") or [])
    required_flags_any = set(filters.get("requiredRiskFlagsAny") or [])
    required_flags_all = set(filters.get("requiredRiskFlagsAll") or [])
    excluded_flags_any = set(filters.get("excludedRiskFlagsAny") or [])
    indoor_outdoor = filters.get("indoorOutdoor")

    matched = []
    for plant in plants_data:
        if statuses and plant.get("status") not in statuses:
            continue
        if plant_ids and plant["plantId"] not in plant_ids:
            continue
        if location_ids and plant.get("locationId") not in location_ids:
            continue
        if sublocation_ids and plant.get("subLocationId") not in sublocation_ids:
            continue
        if indoor_outdoor and plant.get("indoorOutdoor") != indoor_outdoor:
            continue

        plant_flags = set(plant.get("riskFlags") or [])
        if required_flags_any and not (plant_flags & required_flags_any):
            continue
        if required_flags_all and not required_flags_all.issubset(plant_flags):
            continue
        if excluded_flags_any and (plant_flags & excluded_flags_any):
            continue

        matched.append(plant)
    return matched


def _last_matching_event(plant_id, event_types, tz_name):
    if not event_types:
        return None
    matching = events.list_events(plant_id=plant_id, limit=0)
    matching = [event for event in matching if event["type"] in event_types]
    if not matching:
        return None
    return max(matching, key=lambda event: _event_sort_key(event, tz_name))


def _resolve_anchor_datetime(*, profile, schedule, plant_id, event_types, tz_name):
    last_event = _last_matching_event(plant_id, event_types, tz_name)
    event_anchor = _event_anchor_datetime(last_event, tz_name) if last_event else None

    anchor_field = schedule.get("anchorField")
    profile_anchor = _parse_anchor_value(profile.get(anchor_field), tz_name) if anchor_field else None

    anchor_dt = event_anchor
    if profile_anchor and (anchor_dt is None or profile_anchor > anchor_dt):
        anchor_dt = profile_anchor

    return anchor_dt, last_event


def _build_action(
    *,
    rule,
    plant,
    task_type,
    ctx,
    urgency,
    confidence,
    reason,
    baseline_interval,
    days_since,
    suggested_action,
    confirm_event_type,
    due_at=None,
    program_id=None,
    extra=None,
):
    action = {
        "type": task_type,
        "ruleId": rule["ruleId"],
        "plantId": plant["plantId"],
        "displayName": plant["displayName"],
        "locationId": plant.get("locationId"),
        "subLocationId": plant.get("subLocationId"),
        "programId": program_id,
        "urgency": urgency,
        "confidence": confidence,
        "reason": reason,
        "daysSinceLastEvent": round(days_since, 1) if days_since is not None else None,
        "baselineInterval": baseline_interval,
        "dueAt": due_at,
        "riskFlags": plant.get("riskFlags", []),
        "irrigationEffectiveState": plant.get("irrigationEffectiveState"),
        "suggestedAction": suggested_action,
        "confirmEventType": confirm_event_type,
    }
    if extra:
        action.update(extra)
    action["taskId"] = _task_id_for_action(action)
    return action


def _confidence_from_outputs(outputs, ctx):
    if ctx["weatherProvided"]:
        return outputs.get("confidenceWhenWeatherProvided", outputs.get("defaultConfidence", "high"))
    return outputs.get("confidenceWithoutWeather", outputs.get("defaultConfidence", "medium"))


def _resolve_interval_value(source, schedule):
    raw_interval = _first_present(source, schedule.get("intervalFields", ["cadenceDays", "intervalDays"]))
    fallback = None if schedule.get("requireExplicitInterval") else schedule.get("fallbackIntervalDays", [7, 14])
    interval = _normalise_interval(raw_interval, fallback)
    return raw_interval, interval


def _evaluate_profile_interval(
    *,
    plants_data,
    rule,
    ctx,
    seasonal=False,
    programs=False,
):
    actions = []
    no_action = []
    filters = _rule_filters(rule)
    outputs = rule.get("outputs", {})
    history = rule.get("history", {})
    schedule = rule.get("schedule", {})
    profile_type = rule["profileType"]
    confidence = _confidence_from_outputs(outputs, ctx)
    evaluated_at_dt = _parse_iso(ctx["evaluatedAt"])
    tz_name = ctx.get("timezone") or config.load_config().get("timezone", "UTC")

    for plant in _matching_plants(plants_data, filters):
        profile = _profile_for_plant(profile_type, plant)
        if not profile:
            continue

        if programs:
            programs_field = schedule.get("programsField", "recurringPrograms")
            for program in profile.get(programs_field, []):
                _evaluate_profile_program(
                    actions=actions,
                    no_action=no_action,
                    rule=rule,
                    plant=plant,
                    program=program,
                    history=history,
                    schedule=schedule,
                    outputs=outputs,
                    ctx=ctx,
                    confidence=confidence,
                )
            continue

        active_months_field = schedule.get("activeMonthsField")
        active_months = profile.get(active_months_field) if active_months_field else None
        active_window_start = None
        if active_months:
            window, active_window_start, _window_end = _active_window_bounds(active_months, evaluated_at_dt)
            if not window:
                no_action.append(
                    {
                        "plantId": plant["plantId"],
                        "displayName": plant["displayName"],
                        "ruleId": rule["ruleId"],
                        "reason": f"Not active in month {ctx['month']}",
                    }
                )
                continue

        if seasonal:
            seasonal_field = schedule.get("seasonalIntervalsField", "seasonalBaseline")
            interval_field = schedule.get("seasonalIntervalField", "baseIntervalDays")
            season_data = (profile.get(seasonal_field) or {}).get(ctx["season"]) or {}
            raw_interval = season_data.get(interval_field)
            fallback = None if schedule.get("requireExplicitInterval") else schedule.get("fallbackIntervalDays", [7, 14])
            interval = _normalise_interval(raw_interval, fallback)
        else:
            raw_interval, interval = _resolve_interval_value(profile, schedule)

        if interval is None:
            no_action.append(
                {
                    "plantId": plant["plantId"],
                    "displayName": plant["displayName"],
                    "ruleId": rule["ruleId"],
                    "reason": "Profile has no explicit interval configured",
                }
            )
            continue

        event_types = _event_types_from(history.get("eventTypes"))
        anchor_dt, last_evt = _resolve_anchor_datetime(
            profile=profile,
            schedule=schedule,
            plant_id=plant["plantId"],
            event_types=event_types,
            tz_name=tz_name,
        )
        interval_unit = schedule.get("intervalUnit", "days")
        due_min_dt = _add_interval(anchor_dt, interval[0], interval_unit) if anchor_dt else evaluated_at_dt
        due_max_dt = _add_interval(anchor_dt, interval[1], interval_unit) if anchor_dt else evaluated_at_dt
        if active_window_start and anchor_dt is not None and due_min_dt < active_window_start:
            due_min_dt = active_window_start

        urgency, reason, days = _determine_urgency(
            anchor_dt,
            due_min_dt,
            due_max_dt,
            _format_interval_label(interval, interval_unit),
            evaluated_at_dt,
        )
        if urgency is None:
            no_action.append(
                {
                    "plantId": plant["plantId"],
                    "displayName": plant["displayName"],
                    "ruleId": rule["ruleId"],
                    "reason": (
                        f"Within baseline interval ({days:.0f} days, baseline {_format_interval_label(interval, interval_unit)})"
                        if days is not None
                        else "Recently checked"
                    ),
                }
            )
            continue

        suggested_action = outputs.get("suggestedAction", rule.get("taskType"))
        if plant.get("status") == "recovering":
            suggested_action = outputs.get("recoveringSuggestedAction", suggested_action)
            urgency = _ensure_minimum_urgency(
                urgency,
                outputs.get("recoveringMinimumUrgency"),
            )

        if days is None and outputs.get("noHistoryReason"):
            reason = outputs["noHistoryReason"]

        actions.append(
            _build_action(
                rule=rule,
                plant=plant,
                task_type=rule["taskType"],
                ctx=ctx,
                urgency=urgency,
                confidence=confidence,
                reason=reason,
                baseline_interval=interval,
                days_since=days,
                suggested_action=suggested_action,
                confirm_event_type=history.get("confirmEventType"),
                due_at=due_min_dt.astimezone(timezone.utc).isoformat() if due_min_dt else None,
            )
        )

    return actions, no_action


def _evaluate_profile_program(
    *,
    actions,
    no_action,
    rule,
    plant,
    program,
    history,
    schedule,
    outputs,
    ctx,
    confidence,
):
    program_filters = program.get("filters", {})
    if plant not in _matching_plants([plant], program_filters):
        return

    active_months = program.get(schedule.get("activeMonthsField", "activeMonths")) or []
    disabled_months = program.get(schedule.get("disabledMonthsField", "disabledMonths")) or []
    reduced_months = program.get(schedule.get("reducedMonthsField", "reducedMonths")) or []

    if disabled_months and ctx["month"] in disabled_months:
        return
    evaluated_at_dt = _parse_iso(ctx["evaluatedAt"])
    tz_name = ctx.get("timezone") or config.load_config().get("timezone", "UTC")
    active_window_start = None
    if active_months:
        window, active_window_start, _window_end = _active_window_bounds(active_months, evaluated_at_dt)
        if not window:
            no_action.append(
                {
                    "plantId": plant["plantId"],
                    "displayName": plant["displayName"],
                    "ruleId": rule["ruleId"],
                    "programId": program.get("programId"),
                    "reason": f"Program not active in month {ctx['month']}",
                }
            )
            return

    raw_interval, interval = _resolve_interval_value(program, schedule)
    if interval is None:
        no_action.append(
            {
                "plantId": plant["plantId"],
                "displayName": plant["displayName"],
                "ruleId": rule["ruleId"],
                "programId": program.get("programId"),
                "reason": "Program has no explicit interval configured",
            }
        )
        return

    event_types = _event_types_from(program.get("eventTypes")) or _event_types_from(history.get("eventTypes"))
    confirm_event_type = program.get("confirmEventType") or history.get("confirmEventType")
    if confirm_event_type and confirm_event_type not in event_types:
        event_types.append(confirm_event_type)

    anchor_dt, last_evt = _resolve_anchor_datetime(
        profile=program,
        schedule=schedule,
        plant_id=plant["plantId"],
        event_types=event_types,
        tz_name=tz_name,
    )
    interval_unit = schedule.get("intervalUnit", "days")
    due_min_dt = _add_interval(anchor_dt, interval[0], interval_unit) if anchor_dt else evaluated_at_dt
    due_max_dt = _add_interval(anchor_dt, interval[1], interval_unit) if anchor_dt else evaluated_at_dt
    if active_window_start and anchor_dt is not None and due_min_dt < active_window_start:
        due_min_dt = active_window_start

    urgency, reason, days = _determine_urgency(
        anchor_dt,
        due_min_dt,
        due_max_dt,
        _format_interval_label(interval, interval_unit),
        evaluated_at_dt,
    )
    if urgency is None:
        no_action.append(
            {
                "plantId": plant["plantId"],
                "displayName": plant["displayName"],
                "ruleId": rule["ruleId"],
                "programId": program.get("programId"),
                "reason": (
                    f"{program.get('displayName', 'Program')} completed {days:.0f} days ago "
                    f"(baseline {_format_interval_label(interval, interval_unit)})"
                    if days is not None
                    else "Program recently completed"
                ),
            }
        )
        return

    if ctx["month"] in reduced_months:
        urgency = outputs.get("reducedMonthUrgency", "low")

    if days is None and outputs.get("programNoHistoryReason"):
        reason = outputs["programNoHistoryReason"]
    elif days is None:
        reason = f"No {program.get('displayName', 'program').lower()} history — initial action recommended"
    else:
        reason = (
            f"{program.get('displayName', 'Program')} due "
            f"({days:.0f} days since last, baseline {_format_interval_label(interval, interval_unit)})"
        )

    actions.append(
        _build_action(
            rule=rule,
            plant=plant,
            task_type=program.get("taskType") or rule["taskType"],
            ctx=ctx,
            urgency=urgency,
            confidence=confidence,
            reason=reason,
            baseline_interval=interval,
            days_since=days,
            suggested_action=program.get("suggestedAction") or outputs.get("suggestedAction"),
            confirm_event_type=confirm_event_type,
            due_at=due_min_dt.astimezone(timezone.utc).isoformat() if due_min_dt else None,
            program_id=program.get("programId"),
            extra={"programDisplayName": program.get("displayName")},
        )
    )


def _eval_seasonal_profile_interval(plants_data, rule, ctx, cfg):
    return _evaluate_profile_interval(
        plants_data=plants_data,
        rule=rule,
        ctx=ctx,
        seasonal=True,
    )


def _eval_profile_interval(plants_data, rule, ctx, cfg):
    return _evaluate_profile_interval(
        plants_data=plants_data,
        rule=rule,
        ctx=ctx,
        seasonal=False,
    )


def _eval_profile_program_interval(plants_data, rule, ctx, cfg):
    return _evaluate_profile_interval(
        plants_data=plants_data,
        rule=rule,
        ctx=ctx,
        programs=True,
    )


def _eval_profile_month_window(plants_data, rule, ctx, cfg):
    actions = []
    no_action = []
    filters = _rule_filters(rule)
    outputs = rule.get("outputs", {})
    history = rule.get("history", {})
    schedule = rule.get("schedule", {})
    confidence = _confidence_from_outputs(outputs, ctx)
    evaluated_at_dt = _parse_iso(ctx["evaluatedAt"])
    tz_name = ctx.get("timezone") or config.load_config().get("timezone", "UTC")

    for plant in _matching_plants(plants_data, filters):
        profile = _profile_for_plant(rule["profileType"], plant)
        if not profile:
            continue

        months = profile.get(schedule.get("activeMonthsField", "activeMonths")) or []
        if not months:
            no_action.append(
                {
                    "plantId": plant["plantId"],
                    "displayName": plant["displayName"],
                    "ruleId": rule["ruleId"],
                    "reason": "Profile has no active months configured",
                }
            )
            continue

        window, window_start, window_end = _active_window_bounds(months, evaluated_at_dt)
        if not window:
            no_action.append(
                {
                    "plantId": plant["plantId"],
                    "displayName": plant["displayName"],
                    "ruleId": rule["ruleId"],
                    "reason": f"Not active in month {ctx['month']}",
                }
            )
            continue

        event_types = _event_types_from(history.get("eventTypes"))
        confirm_event_type = history.get("confirmEventType")
        if confirm_event_type and confirm_event_type not in event_types:
            event_types.append(confirm_event_type)
        last_evt = _last_matching_event(plant["plantId"], event_types, tz_name)
        last_anchor = _event_anchor_datetime(last_evt, tz_name) if last_evt else None
        days = _days_since(last_anchor, evaluated_at_dt)

        if last_anchor and window_start <= last_anchor < window_end:
            no_action.append(
                {
                    "plantId": plant["plantId"],
                    "displayName": plant["displayName"],
                    "ruleId": rule["ruleId"],
                    "reason": "Already completed in the current seasonal window",
                }
            )
            continue

        actions.append(
            _build_action(
                rule=rule,
                plant=plant,
                task_type=rule["taskType"],
                ctx=ctx,
                urgency=outputs.get("windowUrgency", "medium"),
                confidence=confidence,
                reason="Active seasonal window with no completion recorded yet",
                baseline_interval=None,
                days_since=days,
                suggested_action=outputs.get("suggestedAction", rule.get("taskType")),
                confirm_event_type=confirm_event_type,
                due_at=window_start.astimezone(timezone.utc).isoformat(),
            )
        )

    return actions, no_action


# ---------------------------------------------------------------------------
# Auto-irrigation pre-pass
# ---------------------------------------------------------------------------

def _parse_local_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _season_for_date(value):
    return get_season(value.month)


def _auto_schedule_for_date(system, run_date):
    schedule = system.get("autoSchedule")
    if not schedule:
        return None

    season = _season_for_date(run_date)
    seasonal_schedule = schedule.get("seasonalSchedule") or {}
    season_entry = seasonal_schedule.get(season)
    if season_entry is not None:
        if season_entry.get("enabled", True) is False:
            return {"enabled": False, "cadenceDays": None, "season": season}
        cadence_days = season_entry.get("cadenceDays") or schedule.get("cadenceDays")
    else:
        cadence_days = schedule.get("cadenceDays")

    return {
        "enabled": True,
        "cadenceDays": cadence_days,
        "season": season,
    }


def _auto_irrigation_events_for_system(system_id, tz_name):
    all_events = events.list_events(limit=0, tz_name=tz_name)
    return [
        event
        for event in all_events
        if event.get("type") == "watering_confirmed"
        and (event.get("details") or {}).get("auto") is True
        and (event.get("details") or {}).get("irrigationSystemId") == system_id
    ]


def _last_auto_irrigation_date(system_id, tz_name):
    matching = _auto_irrigation_events_for_system(system_id, tz_name)
    if not matching:
        return None
    latest = max(matching, key=lambda event: _event_sort_key(event, tz_name))
    return _parse_local_date(latest.get("effectiveDateLocal"))


def _existing_auto_irrigation_dates(system_id, tz_name):
    dates = set()
    for event in _auto_irrigation_events_for_system(system_id, tz_name):
        effective_date = _parse_local_date(event.get("effectiveDateLocal"))
        if effective_date:
            dates.add(effective_date)
    return dates


def _eligible_auto_irrigation_plant_ids(plants_data, system):
    system_id = system["irrigationSystemId"]
    exceptions = set(system.get("manualExceptionPlantIds") or [])
    plant_ids = []
    for plant in plants_data:
        if plant.get("irrigationSystemId") != system_id:
            continue
        if plant.get("attachedToIrrigation") is not True:
            continue
        if plant.get("plantId") in exceptions:
            continue
        if plant.get("status") not in {"active", "recovering"}:
            continue
        if plant.get("irrigationMode") == "manual":
            continue
        plant_ids.append(plant["plantId"])
    return plant_ids


def _missed_auto_irrigation_dates(system, last_run_date, evaluated_date):
    cap_start = evaluated_date - timedelta(days=30)
    anchor_date = last_run_date or cap_start
    cursor = anchor_date
    missed_dates = []

    while True:
        schedule = _auto_schedule_for_date(system, cursor)
        cadence_days = (schedule or {}).get("cadenceDays") or (system.get("autoSchedule") or {}).get("cadenceDays")
        if not cadence_days:
            return missed_dates

        candidate = cursor + timedelta(days=cadence_days)
        if candidate > evaluated_date:
            return missed_dates

        if candidate >= cap_start:
            missed_dates.append(candidate)
        cursor = candidate


def _is_today_rain_skip(system, ctx, run_date, evaluated_date):
    schedule = system.get("autoSchedule") or {}
    weather = ctx.get("weather") or {}
    condition = str(weather.get("condition", "")).strip().lower()
    return (
        schedule.get("skipOnRain") is True
        and run_date == evaluated_date
        and condition == "rain"
    )


def _run_auto_irrigation(data_dir, ctx, dry_run):
    """Emit automatic watering confirmations before care rules evaluate."""
    del data_dir  # Store helpers resolve PLANT_DATA_DIR internally.

    report = {
        "emittedEvents": [],
        "backfilledDates": [],
        "skippedSystems": [],
    }
    backfilled_dates = set()
    tz_name = ctx.get("timezone") or config.load_config().get("timezone", "UTC")
    evaluated_at = _parse_iso(ctx["evaluatedAt"])
    if evaluated_at is None:
        return report
    evaluated_date = evaluated_at.date()

    systems = store.read_or_default("irrigation_systems.json").get("irrigationSystems", [])
    plants_data = store.read("plants.json")["plants"]

    for system in systems:
        system_id = system["irrigationSystemId"]
        if system.get("enabled") is not True:
            if system.get("autoSchedule") is not None:
                report["skippedSystems"].append(
                    {"systemId": system_id, "reason": "enabled=false"}
                )
            continue
        if not system.get("autoSchedule"):
            continue

        existing_dates = _existing_auto_irrigation_dates(system_id, tz_name)
        last_run_date = max(existing_dates) if existing_dates else _last_auto_irrigation_date(system_id, tz_name)
        for run_date in _missed_auto_irrigation_dates(system, last_run_date, evaluated_date):
            if run_date in existing_dates:
                continue

            schedule = _auto_schedule_for_date(system, run_date)
            if schedule and schedule.get("enabled") is False:
                report["skippedSystems"].append(
                    {
                        "systemId": system_id,
                        "reason": "season_disabled",
                        "date": run_date.isoformat(),
                        "season": schedule.get("season"),
                    }
                )
                continue

            if _is_today_rain_skip(system, ctx, run_date, evaluated_date):
                report["skippedSystems"].append(
                    {
                        "systemId": system_id,
                        "reason": "weather_rain",
                        "date": run_date.isoformat(),
                    }
                )
                continue

            plant_ids = _eligible_auto_irrigation_plant_ids(plants_data, system)
            if not plant_ids:
                report["skippedSystems"].append(
                    {
                        "systemId": system_id,
                        "reason": "no_eligible_plants",
                        "date": run_date.isoformat(),
                    }
                )
                continue

            event_id = None
            if not dry_run:
                event = events.log_event(
                    event_type="watering_confirmed",
                    source="auto_irrigation",
                    plant_ids=plant_ids,
                    scope=f"auto_irrigation:{system_id}",
                    details={"irrigationSystemId": system_id, "auto": True},
                    effective_date=run_date.isoformat(),
                    effective_precision="day",
                )
                event_id = event["eventId"]

            report["emittedEvents"].append(
                {
                    "eventId": event_id,
                    "systemId": system_id,
                    "effectiveDateLocal": run_date.isoformat(),
                    "plantCount": len(plant_ids),
                }
            )
            backfilled_dates.add(run_date.isoformat())

    report["backfilledDates"] = sorted(backfilled_dates)
    return report


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

ENGINE_EVALUATORS = {
    "seasonal_profile_interval": _eval_seasonal_profile_interval,
    "profile_interval": _eval_profile_interval,
    "profile_program_interval": _eval_profile_program_interval,
    "profile_month_window": _eval_profile_month_window,
}


def _resolve_rule_evaluator(rule):
    return ENGINE_EVALUATORS.get(rule.get("engine"))


def evaluate(*, weather=None, dry_run=False):
    """Run the full care evaluation."""
    cfg = config.load_config()
    if cfg.get("evaluationDefaults", {}).get("weatherRequired") and weather is None:
        raise ValueError("Weather context is required by config.json for evaluation.")
    tz_name = cfg.get("timezone", "UTC")
    ctx = get_current_context(weather=weather, tz_name=tz_name)
    push_config = cfg.get("pushPolicy", {})
    auto_irrigation = _run_auto_irrigation(config.get_data_dir(), ctx, dry_run)

    plants_data = store.read("plants.json")["plants"]
    locations_data = store.read_or_default("locations.json").get("locations", [])
    microzones_data = store.read_or_default("microzones.json").get("microzones", [])
    loc_names = {loc["locationId"]: loc.get("displayName") for loc in locations_data}
    mz_names = {mz["microzoneId"]: mz.get("displayName") for mz in microzones_data}
    care_rules = store.read("care_rules.json")["rules"]
    open_tasks = {task["taskId"]: task for task in reminders.list_tasks(status="open")}

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
        task_id = action["taskId"]
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
                due_at=action.get("dueAt"),
                managed_by_rule_id=action.get("ruleId"),
                program_id=action.get("programId"),
                confirm_event_type=action.get("confirmEventType"),
            )

        if existing_task and existing_task["status"] == "open":
            if _should_push(existing_task, ctx, push_config):
                pushable_actions.append(action)
                state_changes["updated"].append(task_id)
                if not dry_run:
                    reminders.mark_reminded(task_id)
            else:
                suppressed_actions.append(
                    {
                        **action,
                        "suppressedBy": "push_policy",
                        "lastReminderAt": existing_task.get("lastReminderAt"),
                    }
                )
        else:
            pushable_actions.append(action)
            state_changes["opened"].append(task_id)
            if not dry_run:
                reminders.mark_reminded(task_id)

    for task_id, task in open_tasks.items():
        is_managed = bool(task.get("managedByRuleId")) or task.get("type") in LEGACY_MANAGED_TASK_TYPES
        if is_managed and task_id not in due_task_ids:
            state_changes["closed"].append(task_id)
            if not dry_run:
                reminders.expire_task(task_id, reason="No longer due after evaluation")

    for action in pushable_actions + suppressed_actions:
        action["locationDisplayName"] = loc_names.get(action.get("locationId"))
        action["subLocationDisplayName"] = mz_names.get(action.get("subLocationId"))

    result = {
        "evaluatedAt": ctx["evaluatedAt"],
        "context": ctx,
        "actions": pushable_actions,
        "suppressedActions": suppressed_actions,
        "noAction": all_no_action,
        "stateChanges": state_changes,
        "autoIrrigation": auto_irrigation,
        "dryRun": dry_run,
        "summary": {
            "totalActions": len(pushable_actions),
            "totalSuppressed": len(suppressed_actions),
            "totalNoAction": len(all_no_action),
            "byType": {},
        },
    }

    for action in pushable_actions:
        task_type = action["type"]
        result["summary"]["byType"][task_type] = result["summary"]["byType"].get(task_type, 0) + 1

    return result


def _project_open_task_state(snapshot, open_tasks):
    projected = {task["taskId"]: dict(task) for task in open_tasks}

    for task_id in snapshot["stateChanges"]["closed"]:
        projected.pop(task_id, None)

    for action in snapshot["actions"] + snapshot["suppressedActions"]:
        existing = projected.get(action["taskId"], {})
        projected[action["taskId"]] = {
            **existing,
            "taskId": action["taskId"],
            "type": action["type"],
            "status": "open",
            "plantId": action.get("plantId"),
            "dueAt": action.get("dueAt"),
            "lastReason": action.get("reason"),
            "pushCount": existing.get("pushCount", 0),
        }

    projected_tasks = list(projected.values())
    projected_tasks.sort(key=lambda task: task.get("dueAt") or task.get("createdAt", ""))
    return projected_tasks


def quick_status():
    """Quick status: what is due right now without mutating reminder state."""
    snapshot = evaluate(dry_run=True)
    open_tasks = reminders.list_tasks(status="open")
    projected_open_tasks = _project_open_task_state(snapshot, open_tasks)

    return {
        "evaluatedAt": snapshot["evaluatedAt"],
        "openTasks": len(projected_open_tasks),
        "dueNow": snapshot["summary"]["totalActions"],
        "suppressedNow": snapshot["summary"]["totalSuppressed"],
        "tasks": snapshot["actions"],
        "openTaskState": [
            {
                "taskId": task["taskId"],
                "type": task["type"],
                "plantId": task.get("plantId"),
                "pushCount": task.get("pushCount", 0),
                "lastReason": task.get("lastReason"),
                "dueAt": task.get("dueAt"),
            }
            for task in projected_open_tasks
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
            for task in result["tasks"]:
                print(f"  [{task['urgency']:<8}] {task['taskId']:<60} {task['displayName']}")
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
            print(
                f"Season: {result['context']['season']}, "
                f"Weather: {'yes' if result['context']['weatherProvided'] else 'no'}"
            )
            print(f"\nActions ({result['summary']['totalActions']}):")
            for action in result["actions"]:
                print(
                    f"  [{action['urgency']:<8}] {action['type']:<25} "
                    f"{action['displayName']:<25} {action.get('reason', '')[:50]}"
                )
            if not result["actions"]:
                print("  (none)")
            print(f"\nNo action ({result['summary']['totalNoAction']}): use --json for details")

    else:
        print("Usage: plant_mgmt eval {run|status} [--weather JSON] [--dry-run] [--json]")
