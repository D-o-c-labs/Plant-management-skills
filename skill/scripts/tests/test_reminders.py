import json
import io
import unittest
from contextlib import redirect_stdout

from test_support import plant_test_env, read_json, write_json

from plant_mgmt import events
from plant_mgmt import profiles
from plant_mgmt import registry
from plant_mgmt import reminders
from plant_mgmt_cli import build_parser


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
                effective_date="2026-03-18",
                effective_precision="day",
            )

            self.assertEqual(task["status"], "done")
            self.assertEqual(event["type"], "watering_confirmed")
            self.assertEqual(event["effectiveDateLocal"], "2026-03-18")

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

    def test_confirm_rejects_legacy_neem_task_without_repair(self):
        with plant_test_env():
            registry.add_location(location_id="sunroom", name="Sunroom", loc_type="room")
            plant = registry.add_plant(name="Lemon", location_id="sunroom")
            task_id = f"neem:{plant['plantId']}"

            reminders.open_task(
                task_id=task_id,
                task_type="neem",
                plant_id=plant["plantId"],
                location_id="sunroom",
                reason="Legacy standalone neem reminder",
            )

            with self.assertRaises(ValueError):
                reminders.confirm_task(task_id, details="Applied neem")

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

    def test_repair_state_converts_legacy_neem_task(self):
        with plant_test_env() as data_dir:
            registry.add_location(location_id="atrium", name="Atrium", loc_type="room")
            plant = registry.add_plant(name="Lime", location_id="atrium", indoor_outdoor="indoor")
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

            write_json(
                data_dir / "reminder_state.json",
                {
                    "version": 1,
                    "tasks": {
                        f"neem:{plant['plantId']}": {
                            "taskId": f"neem:{plant['plantId']}",
                            "type": "neem",
                            "status": "open",
                            "plantId": plant["plantId"],
                            "locationId": "atrium",
                            "createdAt": "2026-03-01T08:00:00+00:00",
                        }
                    },
                    "meta": {},
                },
            )

            result = reminders.repair_state()

            self.assertTrue(result["changed"])
            reminder_state = read_json(data_dir / "reminder_state.json")
            converted_task_id = (
                f"neem_treatment:pest_recurring_programs:{plant['plantId']}:neem_cycle"
            )
            self.assertEqual(reminder_state["version"], 2)
            self.assertIn(converted_task_id, reminder_state["tasks"])
            self.assertNotIn(f"neem:{plant['plantId']}", reminder_state["tasks"])

    def test_reminders_cli_confirm_accepts_effective_time_flags(self):
        with plant_test_env():
            registry.add_location(location_id="hall", name="Hall", loc_type="room")
            plant = registry.add_plant(name="Ficus", location_id="hall", indoor_outdoor="indoor")
            task_id = f"watering_check:watering_profiles:{plant['plantId']}"

            reminders.open_task(
                task_id=task_id,
                task_type="watering_check",
                plant_id=plant["plantId"],
                location_id="hall",
                reason="Due for watering",
                managed_by_rule_id="watering_profiles",
                confirm_event_type="watering_confirmed",
            )

            parser = build_parser()
            args = parser.parse_args(
                [
                    "--json",
                    "reminders",
                    "confirm",
                    task_id,
                    "--details",
                    "Watered in the morning",
                    "--effective-date",
                    "2026-03-18",
                    "--effective-precision",
                    "part_of_day",
                    "--effective-part-of-day",
                    "morning",
                ]
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                args.func(args)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["event"]["effectiveDateLocal"], "2026-03-18")
            self.assertEqual(payload["event"]["effectivePrecision"], "part_of_day")
            self.assertEqual(payload["event"]["effectivePartOfDay"], "morning")


if __name__ == "__main__":
    unittest.main()
