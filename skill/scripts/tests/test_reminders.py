import unittest

from test_support import plant_test_env, read_json

from plant_mgmt import events
from plant_mgmt import profiles
from plant_mgmt import registry
from plant_mgmt import reminders


class RemindersTest(unittest.TestCase):
    def test_confirm_watering_task_logs_canonical_event_type(self):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            plant = registry.add_plant(name="Basil", location_id="balcony")
            task_id = f"watering_check:watering_profiles:{plant['plantId']}"

            reminders.open_task(
                task_id=task_id,
                task_type="watering_check",
                plant_id=plant["plantId"],
                location_id="balcony",
                reason="Due for watering",
                managed_by_rule_id="watering_profiles",
                confirm_event_type="watering_confirmed",
            )

            task, event = reminders.confirm_task(
                task_id,
                details="Watered thoroughly",
            )

            self.assertEqual(task["status"], "done")
            self.assertEqual(event["type"], "watering_confirmed")

    def test_confirm_task_prefers_task_level_confirm_event_type(self):
        with plant_test_env():
            registry.add_location(location_id="studio", name="Studio", loc_type="room")
            plant = registry.add_plant(name="Ficus", location_id="studio")
            task_id = f"soap_treatment:pest_recurring_programs:{plant['plantId']}:soap_cycle"

            reminders.open_task(
                task_id=task_id,
                task_type="soap_treatment",
                plant_id=plant["plantId"],
                location_id="studio",
                reason="Soap treatment due",
                managed_by_rule_id="pest_recurring_programs",
                program_id="soap_cycle",
                confirm_event_type="soap_confirmed",
            )

            task, event = reminders.confirm_task(task_id, details="Applied soap")

            self.assertEqual(task["status"], "done")
            self.assertEqual(event["type"], "soap_confirmed")

    def test_confirm_rejects_non_open_tasks_without_logging_events(self):
        with plant_test_env() as data_dir:
            registry.add_location(location_id="terrace", name="Terrace", loc_type="balcony")
            plant = registry.add_plant(name="Mint", location_id="terrace")

            for status in ("done", "cancelled", "expired"):
                task_id = f"watering_check:watering_profiles:{plant['plantId']}:{status}"
                reminders.open_task(
                    task_id=task_id,
                    task_type="watering_check",
                    plant_id=plant["plantId"],
                    location_id="terrace",
                    reason="Due for watering",
                    managed_by_rule_id="watering_profiles",
                    confirm_event_type="watering_confirmed",
                )
                if status == "done":
                    reminders.confirm_task(task_id, details="Already watered")
                elif status == "cancelled":
                    reminders.cancel_task(task_id, reason="Skipped")
                else:
                    reminders.expire_task(task_id, reason="No longer due")

                before = len(read_json(data_dir / "events.json")["events"])
                with self.assertRaises(ValueError):
                    reminders.confirm_task(task_id, details="Should fail")
                after = len(read_json(data_dir / "events.json")["events"])
                self.assertEqual(before, after)

    def test_confirm_repotting_task_updates_profile_anchor(self):
        with plant_test_env() as data_dir:
            registry.add_location(location_id="veranda", name="Veranda", loc_type="balcony")
            plant = registry.add_plant(name="Lemon", location_id="veranda")
            profiles.set_profile(
                "repotting",
                plant["plantId"],
                {
                    "profileId": "repot:lemon",
                    "repottingIntervalYears": [1, 2],
                    "bestMonths": [3, 4, 5],
                },
            )
            task_id = f"repotting_check:repotting_profiles:{plant['plantId']}"
            reminders.open_task(
                task_id=task_id,
                task_type="repotting_check",
                plant_id=plant["plantId"],
                location_id="veranda",
                reason="Repotting season is active",
                managed_by_rule_id="repotting_profiles",
                confirm_event_type="repotting_confirmed",
            )

            reminders.confirm_task(task_id, details="Repotted into a larger pot")

            profile = profiles.get_profile("repotting", "repot:lemon")
            latest_event = events.get_last_event(plant["plantId"], event_type="repotting_confirmed")
            self.assertEqual(profile["lastRepottedAt"], latest_event["effectiveDateLocal"])


if __name__ == "__main__":
    unittest.main()
