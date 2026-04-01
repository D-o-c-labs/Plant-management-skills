import unittest

from test_support import plant_test_env

from plant_mgmt import registry
from plant_mgmt import reminders


class RemindersTest(unittest.TestCase):
    def test_confirm_watering_task_logs_canonical_event_type(self):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            plant = registry.add_plant(name="Basil", location_id="balcony")

            reminders.open_task(
                task_id=f"watering_check:{plant['plantId']}",
                task_type="watering_check",
                plant_id=plant["plantId"],
                location_id="balcony",
                reason="Due for watering",
            )

            task, event = reminders.confirm_task(
                f"watering_check:{plant['plantId']}",
                details="Watered thoroughly",
            )

            self.assertEqual(task["status"], "done")
            self.assertEqual(event["type"], "watering_confirmed")


if __name__ == "__main__":
    unittest.main()
