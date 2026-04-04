import json
import tempfile
import unittest
from pathlib import Path

from test_support import plant_test_env, read_json, write_json

from plant_mgmt import init
from plant_mgmt import profiles
from plant_mgmt import registry


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

    def test_migrate_normalizes_legacy_reminder_state_and_converts_neem_tasks(self):
        with plant_test_env() as data_dir:
            registry.add_location(location_id="greenhouse", name="Greenhouse", loc_type="room")
            plant = registry.add_plant(name="Lemon", location_id="greenhouse", indoor_outdoor="indoor")
            profiles.set_profile(
                "pest",
                plant["plantId"],
                {
                    "recurringPrograms": [
                        {
                            "programId": "neem_cycle",
                            "displayName": "Neem cycle",
                            "taskType": "neem_treatment",
                            "confirmEventType": "neem_confirmed",
                            "cadenceDays": [12, 15],
                        }
                    ]
                },
            )

            with tempfile.TemporaryDirectory(prefix="plant-mgmt-source-") as source_dir:
                source_path = Path(source_dir)
                for filename in (
                    "plants.json",
                    "locations.json",
                    "pest_profiles.json",
                    "events.json",
                    "config.json",
                ):
                    write_json(source_path / filename, read_json(data_dir / filename))

                write_json(
                    source_path / "reminder_state.json",
                    {
                        "version": 1,
                        "tasks": {
                            f"neem:{plant['plantId']}": {
                                "taskId": f"neem:{plant['plantId']}",
                                "type": "neem",
                                "status": "open",
                                "plantId": plant["plantId"],
                                "locationId": "greenhouse",
                                "createdAt": "2026-03-01T08:00:00+00:00",
                            }
                        },
                        "meta": {},
                    },
                )

                result = init.migrate_from_existing(str(source_path))

                self.assertFalse(result["errors"])
                reminder_state = read_json(data_dir / "reminder_state.json")
                self.assertEqual(reminder_state["version"], 2)
                self.assertIn(
                    f"neem_treatment:pest_recurring_programs:{plant['plantId']}:neem_cycle",
                    reminder_state["tasks"],
                )
                self.assertNotIn(f"neem:{plant['plantId']}", reminder_state["tasks"])


if __name__ == "__main__":
    unittest.main()
