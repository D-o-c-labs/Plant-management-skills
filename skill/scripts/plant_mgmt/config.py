"""Configuration management: ENV vars + config.json loading.

Merge order: defaults → config.json → ENV (ENV wins).
"""

import json
import os
from pathlib import Path


# Default configuration values
_DEFAULTS = {
    "timezone": "UTC",
    "locale": "en",
    "pushPolicy": {
        "weekday": {
            "activeHours": [7, 23],
            "minHoursBetweenPushes": {
                "0700-1659": 6,
                "1700-2300": 2,
            },
        },
        "weekend": {
            "activeHours": [7, 23],
            "minHoursBetweenPushes": 2,
        },
    },
    "evaluationDefaults": {
        "weatherRequired": False,
        "dryRunDefault": False,
    },
}

# Maps ENV var names → config keys they override
_ENV_OVERRIDES = {
    "PLANT_TIMEZONE": "timezone",
    "PLANT_LOCALE": "locale",
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override values win."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_data_dir() -> Path:
    """Return the plant data directory from PLANT_DATA_DIR env var."""
    raw = os.environ.get("PLANT_DATA_DIR")
    if not raw:
        raise EnvironmentError(
            "PLANT_DATA_DIR environment variable is required. "
            "Set it to the path where plant JSON data files are stored."
        )
    p = Path(raw).expanduser().resolve()
    return p


def get_skill_dir() -> Path:
    """Return the skill root directory (parent of scripts/).

    Auto-detected from this file's location, or overridden via PLANT_SKILL_DIR.
    """
    override = os.environ.get("PLANT_SKILL_DIR")
    if override:
        return Path(override).expanduser().resolve()
    # Default: this file is at scripts/plant_mgmt/config.py → skill root is ../../..
    return Path(__file__).resolve().parent.parent.parent


def get_schemas_dir() -> Path:
    return get_skill_dir() / "schemas"


def get_seeds_dir() -> Path:
    return get_skill_dir() / "seeds"


def get_api_key(name: str) -> str | None:
    """Return an API key from env, or None if not set."""
    return os.environ.get(name) or None


def load_config() -> dict:
    """Load merged configuration: defaults → config.json → ENV overrides."""
    config = _DEFAULTS.copy()

    # Layer 2: config.json from data dir (if exists)
    try:
        data_dir = get_data_dir()
        config_file = data_dir / "config.json"
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                file_config = json.load(f)
            # Remove version key — it's metadata, not config
            file_config.pop("version", None)
            config = _deep_merge(config, file_config)
    except EnvironmentError:
        pass  # PLANT_DATA_DIR not set yet (e.g. during init)

    # Layer 3: ENV overrides
    for env_var, config_key in _ENV_OVERRIDES.items():
        val = os.environ.get(env_var)
        if val is not None:
            config[config_key] = val

    return config


def get_configured_apis() -> dict:
    """Return dict of configured API names → their keys/credentials."""
    apis = {}

    trefle = get_api_key("TREFLE_API_KEY")
    if trefle:
        apis["trefle"] = {"api_key": trefle}

    perenual = get_api_key("PERENUAL_API_KEY")
    if perenual:
        apis["perenual"] = {"api_key": perenual}

    opb_id = get_api_key("OPENPLANTBOOK_CLIENT_ID")
    opb_secret = get_api_key("OPENPLANTBOOK_CLIENT_SECRET")
    if opb_id and opb_secret:
        apis["openplantbook"] = {"client_id": opb_id, "client_secret": opb_secret}

    tavily = get_api_key("TAVILY_API_KEY")
    if tavily:
        apis["tavily"] = {"api_key": tavily}

    return apis
