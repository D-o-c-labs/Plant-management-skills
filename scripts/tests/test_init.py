import json
import tempfile
import unittest
from pathlib import Path

from test_support import plant_test_env

from plant_mgmt import init


class InitTest(unittest.TestCase):
    def test_migrate_initializes_missing_required_files_from_seeds(self):
        with plant_test_env():
            with tempfile.TemporaryDirectory(prefix="plant-mgmt-source-") as source_dir:
                source_path = Path(source_dir)
                with open(source_path / "plants.json", "w", encoding="utf-8") as f:
                    json.dump({"version": 1, "nextPlantNumericId": 1, "plants": []}, f)

                result = init.migrate_from_existing(str(source_path))

                self.assertIn("plants.json", result["imported"])
                self.assertIn("locations.json", result["initialized"])
                self.assertFalse(result["errors"])


if __name__ == "__main__":
    unittest.main()
