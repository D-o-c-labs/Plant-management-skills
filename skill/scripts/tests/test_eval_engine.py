import unittest

from skills.scripts.plant_mgmt import eval_engine, events, profiles, registry
from skills.scripts.tests.test_support import plant_test_env

from skills.scripts.plant_mgmt import reminders


class EvalEngineTest(unittest.TestCase):
    def test_eval_closes_open_task_when_plant_is_no_longer_due(self):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            plant = registry.add_plant(name="Rosemary", location_id="balcony")
            profiles.set_profile(
                "watering",
                plant["plantId"],
                {
                    "profileId": "watering:rosemary",
                    "baselineSource": "rosemary baseline",
                    "seasonalBaseline": {
                        "winter": {"level": "very_low", "baseIntervalDays": [14, 21]},
                        "spring": {"level": "low", "baseIntervalDays": [6, 10]},
                        "summer": {"level": "medium", "baseIntervalDays": [4, 7]},
                        "autumn": {"level": "low", "baseIntervalDays": [7, 10]},
                    },
                },
            )
            events.log_event(
                event_type="watering_confirmed",
                plant_id=plant["plantId"],
                location_id="balcony",
            )
            reminders.open_task(
                task_id=f"watering_check:{plant['plantId']}",
                task_type="watering_check",
                plant_id=plant["plantId"],
                location_id="balcony",
                reason="Old stale reminder",
            )

            result = eval_engine.evaluate(dry_run=True)

            self.assertEqual(result["summary"]["totalActions"], 0)
            self.assertIn(f"watering_check:{plant['plantId']}", result["stateChanges"]["closed"])


if __name__ == "__main__":
    unittest.main()

