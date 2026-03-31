"""Schema loading and validation using JSON Schema."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from . import config


# Cache loaded schemas
_schema_cache: dict[str, dict] = {}

# Map data filenames → schema filenames
SCHEMA_MAP = {
    "plants.json": "plants.schema.json",
    "locations.json": "locations.schema.json",
    "microzones.json": "microzones.schema.json",
    "irrigation_systems.json": "irrigation_systems.schema.json",
    "watering_profiles.json": "watering_profiles.schema.json",
    "fertilization_profiles.json": "fertilization_profiles.schema.json",
    "repotting_profiles.json": "repotting_profiles.schema.json",
    "pest_profiles.json": "pest_profiles.schema.json",
    "maintenance_profiles.json": "maintenance_profiles.schema.json",
    "healthcheck_profiles.json": "healthcheck_profiles.schema.json",
    "care_rules.json": "care_rules.schema.json",
    "reminder_state.json": "reminder_state.schema.json",
    "events.json": "events.schema.json",
    "config.json": "config.schema.json",
}


def _load_schema(schema_name: str) -> dict:
    """Load a JSON Schema file from the schemas directory."""
    if schema_name in _schema_cache:
        return _schema_cache[schema_name]

    schema_path = config.get_schemas_dir() / schema_name
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")

    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    _schema_cache[schema_name] = schema
    return schema


def get_schema_for_file(filename: str) -> dict | None:
    """Return the JSON Schema for a given data filename, or None if no schema exists."""
    schema_name = SCHEMA_MAP.get(filename)
    if not schema_name:
        return None
    try:
        return _load_schema(schema_name)
    except FileNotFoundError:
        return None


def validate(data: dict, filename: str) -> list[str]:
    """Validate data against the schema for the given filename.

    Returns a list of error messages. Empty list means valid.
    """
    schema = get_schema_for_file(filename)
    if schema is None:
        return []  # No schema = no validation errors

    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"{path}: {error.message}")
    return errors


def validate_or_raise(data: dict, filename: str) -> None:
    """Validate data and raise ValueError if invalid."""
    errors = validate(data, filename)
    if errors:
        error_text = "\n".join(f"  - {e}" for e in errors[:10])
        count_msg = f" (showing first 10 of {len(errors)})" if len(errors) > 10 else ""
        raise ValueError(
            f"Validation failed for {filename}{count_msg}:\n{error_text}"
        )
