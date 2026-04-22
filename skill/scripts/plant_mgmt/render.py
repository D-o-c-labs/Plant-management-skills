"""Render human-readable reminder messages from evaluation actions."""

from __future__ import annotations


_ACTION_LABELS = {
    "en": {
        "water_if_dry": ("💧", "Probable watering"),
        "check_soil_first": ("💧", "Check soil first"),
        "fertilize": ("🌱", "Fertilization"),
        "apply_neem_oil": ("🟤", "Neem treatment"),
        "apply_insecticidal_soap": ("🧴", "Insecticidal soap"),
        "repot_if_rootbound": ("🪴", "Repotting check"),
        "clean_leaves": ("🧹", "Leaf cleaning"),
        "prune_if_needed": ("✂️", "Pruning check"),
        "inspect_plant_health": ("🔍", "Health check"),
    },
    "it": {
        "water_if_dry": ("💧", "Probabile acqua"),
        "check_soil_first": ("💧", "Controlla il terreno"),
        "fertilize": ("🌱", "Concimazione"),
        "apply_neem_oil": ("🟤", "Trattamento neem"),
        "apply_insecticidal_soap": ("🧴", "Sapone insetticida"),
        "repot_if_rootbound": ("🪴", "Controllo rinvaso"),
        "clean_leaves": ("🧹", "Pulizia foglie"),
        "prune_if_needed": ("✂️", "Potatura"),
        "inspect_plant_health": ("🔍", "Controllo salute"),
    },
}

_LOCALE_TEXT = {
    "en": {
        "and": "and",
        "sentence": "{label} for {plant_list} at {location}.",
        "critical_prefix": "⚠️ Urgent: {label}",
        "urgent_tag": "⚠️ urgent",
        "auto_irrigation": "💧 Auto-irrigation logged for {plant_count} plants ({date_count} dates backfilled).",
    },
    "it": {
        "and": "e",
        "sentence": "{label} per {plant_list} a {location}.",
        "critical_prefix": "⚠️ Urgente: {label}",
        "urgent_tag": "⚠️ urgente",
        "auto_irrigation": "💧 Irrigazione automatica registrata per {plant_count} piante ({date_count} date recuperate).",
    },
}

_URGENCY_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


def normalize_locale(locale: str | None) -> str:
    """Normalize locale to a supported base language."""
    if not locale:
        return "en"
    base = locale.strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in _ACTION_LABELS else "en"


def _action_key(action: dict) -> str:
    return action.get("suggestedAction") or action.get("type") or "action"


def _humanize_action(value: str | None) -> str:
    if not value:
        return "Action"
    return value.replace("_", " ").strip().title()


def _label_parts(action: dict, locale: str) -> tuple[str, str]:
    key = _action_key(action)
    return _ACTION_LABELS[locale].get(key, ("", _humanize_action(key)))


def _label(action: dict, locale: str) -> str:
    emoji, text = _label_parts(action, locale)
    return f"{emoji} {text}".strip()


def _location_name(action: dict) -> str:
    return action.get("locationDisplayName") or action.get("locationId") or "Unknown location"


def _plant_name(action: dict) -> str:
    display_name = action.get("displayName") or action.get("plantId") or "Plant"
    sublocation = action.get("subLocationDisplayName")
    if sublocation:
        return f"{display_name} ({sublocation})"
    return display_name


def _join_plant_names(names: list[str], locale: str) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} {_LOCALE_TEXT[locale]['and']} {names[1]}"
    return f"{', '.join(names[:-1])}, {_LOCALE_TEXT[locale]['and']} {names[-1]}"


def _group_urgency(actions: list[dict]) -> int:
    return max(_URGENCY_ORDER.get(action.get("urgency"), -1) for action in actions)


def _sorted_actions(actions: list[dict]) -> list[dict]:
    return sorted(
        actions,
        key=lambda action: (
            -_URGENCY_ORDER.get(action.get("urgency"), -1),
            (action.get("displayName") or action.get("plantId") or "").casefold(),
        ),
    )


def _build_groups(actions: list[dict], locale: str) -> list[dict]:
    grouped = {}
    for action in actions:
        key = (action.get("locationId"), _action_key(action))
        grouped.setdefault(key, []).append(action)

    groups = []
    for group_actions in grouped.values():
        ordered_actions = _sorted_actions(group_actions)
        urgencies = {action.get("urgency") for action in ordered_actions}
        groups.append(
            {
                "actions": ordered_actions,
                "location": _location_name(ordered_actions[0]),
                "label": _label(ordered_actions[0], locale),
                "highest_urgency": _group_urgency(ordered_actions),
                "mixed_urgency": len(urgencies) > 1,
                "all_critical": urgencies == {"critical"},
            }
        )

    return sorted(
        groups,
        key=lambda group: (
            -group["highest_urgency"],
            group["location"].casefold(),
            group["label"].casefold(),
        ),
    )


def _render_auto_irrigation_summary(auto_irrigation: dict | None, locale: str) -> str | None:
    if not auto_irrigation:
        return None
    emitted_events = auto_irrigation.get("emittedEvents") or []
    if not emitted_events:
        return None

    plant_count = sum(event.get("plantCount") or 0 for event in emitted_events)
    date_count = len(auto_irrigation.get("backfilledDates") or [])
    return _LOCALE_TEXT[locale]["auto_irrigation"].format(
        plant_count=plant_count,
        date_count=date_count,
    )


def render_message(
    actions: list[dict],
    *,
    locale: str = "en",
    auto_irrigation: dict | None = None,
) -> str | None:
    """Render a grouped reminder message from evaluation actions."""
    locale = normalize_locale(locale)
    auto_summary = _render_auto_irrigation_summary(auto_irrigation, locale)
    if not actions:
        return auto_summary

    groups = _build_groups(actions, locale)
    text = _LOCALE_TEXT[locale]

    if len(groups) == 1:
        group = groups[0]
        if not group["mixed_urgency"] and len(group["actions"]) <= 2:
            label = group["label"]
            if group["all_critical"]:
                label = text["critical_prefix"].format(label=label)
            plant_list = _join_plant_names([_plant_name(action) for action in group["actions"]], locale)
            message = text["sentence"].format(
                label=label,
                plant_list=plant_list,
                location=group["location"],
            )
            if auto_summary:
                return f"{auto_summary}\n\n{message}"
            return message

    blocks = []
    for group in groups:
        header = group["label"]
        if group["all_critical"]:
            header = text["critical_prefix"].format(label=header)

        lines = [f"{header} — {group['location']}:"]
        for action in group["actions"]:
            plant_line = _plant_name(action)
            if group["mixed_urgency"] and action.get("urgency") == "critical":
                plant_line = f"{plant_line} {text['urgent_tag']}"
            lines.append(f"  • {plant_line}")
        blocks.append("\n".join(lines))

    message = "\n\n".join(blocks)
    if auto_summary:
        return f"{auto_summary}\n\n{message}"
    return message
