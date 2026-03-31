"""Data directory initialization from seed templates."""

import json
import shutil
from pathlib import Path

from . import config
from . import schemas
from . import store


# Files that should exist in a valid data directory
REQUIRED_FILES = [
    "plants.json",
    "locations.json",
    "microzones.json",
    "irrigation_systems.json",
    "watering_profiles.json",
    "fertilization_profiles.json",
    "repotting_profiles.json",
    "pest_profiles.json",
    "maintenance_profiles.json",
    "healthcheck_profiles.json",
    "care_rules.json",
    "reminder_state.json",
    "events.json",
    "config.json",
]


def init_data_dir(*, force: bool = False) -> dict:
    """Initialize the data directory from seed templates.

    Args:
        force: If True, overwrite existing files with seeds.

    Returns:
        Dict with "created", "skipped", "errors" lists.
    """
    data_dir = config.get_data_dir()
    seeds_dir = config.get_seeds_dir()

    data_dir.mkdir(parents=True, exist_ok=True)

    result = {"created": [], "skipped": [], "errors": []}

    for filename in REQUIRED_FILES:
        dest = data_dir / filename
        seed = seeds_dir / filename

        if dest.exists() and not force:
            result["skipped"].append(filename)
            continue

        if not seed.exists():
            result["errors"].append(f"{filename}: seed template not found at {seed}")
            continue

        try:
            shutil.copy2(seed, dest)
            result["created"].append(filename)
        except Exception as e:
            result["errors"].append(f"{filename}: {e}")

    validation = check_data_dir()
    for filename, errors in validation["validation"].items():
        for error in errors:
            result["errors"].append(f"{filename}: {error}")

    return result


def migrate_from_existing(source_dir: str) -> dict:
    """Import data from an existing plant data directory (e.g. OpenClaw workspace).

    Copies all recognized JSON files from source_dir to the configured PLANT_DATA_DIR.
    Validates each file after copying.

    Args:
        source_dir: Path to the existing data directory.

    Returns:
        Dict with "imported", "skipped", "errors" lists.
    """
    source = Path(source_dir).expanduser().resolve()
    data_dir = config.get_data_dir()

    if not source.exists():
        raise FileNotFoundError(f"Source directory not found: {source}")

    data_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "imported": [],
        "initialized": [],
        "skipped": [],
        "validation_warnings": [],
        "errors": [],
    }

    for filename in REQUIRED_FILES:
        source_file = source / filename
        dest = data_dir / filename

        if not source_file.exists():
            seed = config.get_seeds_dir() / filename
            if seed.exists():
                shutil.copy2(seed, dest)
                result["initialized"].append(filename)
            else:
                result["errors"].append(f"{filename}: missing from source and no seed found")
            continue

        try:
            # Read and parse to verify it's valid JSON
            with open(source_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate against schema if one exists
            warnings = schemas.validate(data, filename)
            if warnings:
                result["validation_warnings"].append({
                    "file": filename,
                    "warnings": warnings,
                })

            # Copy the file
            shutil.copy2(source_file, dest)
            result["imported"].append(filename)

        except json.JSONDecodeError as e:
            result["errors"].append(f"{filename}: invalid JSON — {e}")
        except Exception as e:
            result["errors"].append(f"{filename}: {e}")

    # Also copy intake directory if present
    source_intake = source / "intake"
    if source_intake.exists() and source_intake.is_dir():
        dest_intake = data_dir / "intake"
        dest_intake.mkdir(parents=True, exist_ok=True)
        for intake_file in source_intake.iterdir():
            try:
                shutil.copy2(intake_file, dest_intake / intake_file.name)
            except Exception as e:
                result["errors"].append(f"intake/{intake_file.name}: {e}")
        result["imported"].append("intake/")

    validation = check_data_dir()
    for filename, errors in validation["validation"].items():
        for error in errors:
            result["errors"].append(f"{filename}: {error}")

    return result


def check_data_dir() -> dict:
    """Check the health of the data directory.

    Returns:
        Dict with "present", "missing", "validation" results.
    """
    data_dir = config.get_data_dir()

    result = {
        "data_dir": str(data_dir),
        "exists": data_dir.exists(),
        "present": [],
        "missing": [],
        "validation": {},
    }

    if not data_dir.exists():
        result["missing"] = REQUIRED_FILES
        return result

    for filename in REQUIRED_FILES:
        path = data_dir / filename
        if path.exists():
            result["present"].append(filename)
        else:
            result["missing"].append(filename)

    # Validate present files
    result["validation"] = store.validate_all()

    return result
