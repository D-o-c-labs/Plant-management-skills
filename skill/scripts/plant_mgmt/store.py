"""Safe JSON storage with atomic writes and schema validation.

All data file reads and writes go through this module.
Never edit JSON files directly — always use store.read() and store.write().
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

from . import config
from . import schemas


def _data_path(filename: str) -> Path:
    """Resolve full path for a data file."""
    return config.get_data_dir() / filename


def exists(filename: str) -> bool:
    """Check if a data file exists."""
    return _data_path(filename).exists()


def _write_atomic(path: Path, data: dict, *, backup: bool = True) -> None:
    """Write JSON data atomically to a resolved path."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if backup and path.exists():
        bak_path = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak_path)

    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def _attempt_auto_repair(filename: str, path: Path, data: dict) -> tuple[dict, bool]:
    """Repair reminder state in place when a normalized payload becomes valid."""
    if filename != "reminder_state.json" or not isinstance(data, dict):
        return data, False

    from . import reminders

    normalized, changed, _repairs, _warnings = reminders.normalize_state_payload(data)
    if not changed:
        return data, False

    if schemas.validate(normalized, filename):
        return data, False

    _write_atomic(path, normalized, backup=True)
    return normalized, True


def read(filename: str, *, validate: bool = True) -> dict:
    """Read and parse a JSON data file.

    Args:
        filename: Name of the file in the data directory (e.g. "plants.json").
        validate: If True, validate against schema after reading.

    Returns:
        Parsed JSON data as a dict.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If the file contains invalid JSON.
        ValueError: If validation fails.
    """
    path = _data_path(filename)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if validate:
        errors = schemas.validate(data, filename)
        if errors:
            data, repaired = _attempt_auto_repair(filename, path, data)
            if not repaired:
                schemas.validate_or_raise(data, filename)

    return data


def read_or_default(filename: str, *, validate: bool = True) -> dict:
    """Read a data file, or create it from seed if missing.

    If the file doesn't exist, copies the seed template and returns it.
    """
    if exists(filename):
        return read(filename, validate=validate)

    # Try to create from seed
    seed_path = config.get_seeds_dir() / filename
    if seed_path.exists():
        dest = _data_path(filename)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(seed_path, dest)
        return read(filename, validate=validate)

    raise FileNotFoundError(
        f"Data file not found and no seed template available: {filename}"
    )


def write(filename: str, data: dict, *, validate: bool = True, backup: bool = True) -> None:
    """Write data to a JSON file atomically with optional validation.

    Args:
        filename: Name of the file in the data directory.
        data: Data to write.
        validate: If True, validate against schema before writing.
        backup: If True, create a .bak copy of the existing file before overwriting.

    Raises:
        ValueError: If validation fails (data is NOT written).
    """
    if validate:
        schemas.validate_or_raise(data, filename)

    path = _data_path(filename)
    _write_atomic(path, data, backup=backup)


def list_data_files() -> list[str]:
    """List all JSON files in the data directory."""
    try:
        data_dir = config.get_data_dir()
    except EnvironmentError:
        return []
    if not data_dir.exists():
        return []
    return sorted(f.name for f in data_dir.glob("*.json"))


def validate_all() -> dict[str, list[str]]:
    """Validate all data files against their schemas.

    Returns:
        Dict mapping filename → list of error messages. Empty list = valid.
        Files without schemas are included with empty error lists.
    """
    results = {}
    for filename in list_data_files():
        try:
            if filename == "reminder_state.json":
                read(filename, validate=True)
                results[filename] = []
            else:
                data = read(filename, validate=False)
                results[filename] = schemas.validate(data, filename)
        except json.JSONDecodeError as e:
            results[filename] = [f"Invalid JSON: {e}"]
        except ValueError as e:
            results[filename] = [str(e)]
        except Exception as e:
            results[filename] = [f"Read error: {e}"]
    return results
