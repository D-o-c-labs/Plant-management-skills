"""Shared test helpers for the plant management skill."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
SKILL_ROOT = SCRIPTS_DIR.parent
SEEDS_DIR = SKILL_ROOT / "seeds"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@contextmanager
def plant_test_env():
    """Create an isolated PLANT_DATA_DIR populated from seed data."""
    previous_env = {
        "PLANT_DATA_DIR": os.environ.get("PLANT_DATA_DIR"),
        "PLANT_SKILL_DIR": os.environ.get("PLANT_SKILL_DIR"),
    }

    with tempfile.TemporaryDirectory(prefix="plant-mgmt-test-") as tmp_dir:
        data_dir = Path(tmp_dir)
        for seed_file in SEEDS_DIR.glob("*.json"):
            shutil.copy2(seed_file, data_dir / seed_file.name)

        os.environ["PLANT_DATA_DIR"] = str(data_dir)
        os.environ["PLANT_SKILL_DIR"] = str(SKILL_ROOT)

        try:
            yield data_dir
        finally:
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def read_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

