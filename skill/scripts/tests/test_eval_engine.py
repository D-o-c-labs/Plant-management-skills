import unittest
from unittest.mock import patch

from test_support import plant_test_env, read_json, write_json

from plant_mgmt import eval_engine, events, profiles, registry, reminders


FIXED_CONTEXT = {
    "evaluatedAt": "2026-04-01T09:00:00+00:00",
    "timezone": "UTC",
    "season": "spring",
    "month": 4,
    "dayOfWeek": "wednesday",
    "timeLocal": "09:00",
    "hour": 9,
    "isWeekend": False,
    "weatherProvided": False,
    "weather": None,
}

JAN_CONTEXT = {
    "evaluatedAt": "2026-01-15T09:00:00+00:00",
    "timezone": "UTC",
    "season": "winter",
    "month": 1,
    "dayOfWeek": "thursday",
    "timeLocal": "09:00",
    "hour": 9,
    "isWeekend": False,
    "weatherProvided": False,
    "weather": None,
}


class EvalEngineTest(unittest.TestCase):
    def assert_action_display_names(self, action, *, location_name, sublocation_name=None):
        self.assertEqual(action["locationDisplayName"], location_name)
        self.assertEqual(action["subLocationDisplayName"], sublocation_name)

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=FIXED_CONTEXT)
    def test_eval_closes_open_task_when_plant_is_no_longer_due(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="winter_garden", name="Winter Garden", loc_type="room")
            plant = registry.add_plant(name="Rosemary", location_id="winter_garden")
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
                location_id="winter_garden",
            )
            task_id = f"watering_check:watering_profiles:{plant['plantId']}"
            reminders.open_task(
                task_id=task_id,
                task_type="watering_check",
                plant_id=plant["plantId"],
                location_id="winter_garden",
                reason="Old stale reminder",
                managed_by_rule_id="watering_profiles",
                confirm_event_type="watering_confirmed",
            )

            result = eval_engine.evaluate(dry_run=True)

            self.assertEqual(result["summary"]["totalActions"], 0)
            self.assertIn(task_id, result["stateChanges"]["closed"])

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=FIXED_CONTEXT)
    def test_eval_reads_pest_programs_from_profiles_without_zone_specific_code(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="atrium_house", name="Atrium House", loc_type="room")
            plant = registry.add_plant(name="Lemon", location_id="atrium_house", indoor_outdoor="indoor")
            registry.update_plant(plant["plantId"], {"riskFlags": ["spider_mites"]})
            profiles.set_profile(
                "pest",
                plant["plantId"],
                {
                    "knownVulnerabilities": ["spider_mites"],
                    "preventiveTreatments": ["neem oil"],
                    "recurringPrograms": [
                        {
                            "programId": "neem_cycle",
                            "displayName": "Neem cycle",
                            "taskType": "neem_treatment",
                            "confirmEventType": "neem_confirmed",
                            "suggestedAction": "apply_neem_oil",
                            "cadenceDays": [12, 15],
                            "activeMonths": [3, 4, 5, 6, 7, 8, 9, 10],
                            "filters": {"requiredRiskFlagsAny": ["spider_mites"]},
                        }
                    ],
                },
            )

            result = eval_engine.evaluate(dry_run=True)

            self.assertEqual(result["summary"]["totalActions"], 1)
            action = result["actions"][0]
            self.assertEqual(action["type"], "neem_treatment")
            self.assertEqual(action["ruleId"], "pest_recurring_programs")
            self.assertEqual(action["programId"], "neem_cycle")
            self.assertEqual(action["suggestedAction"], "apply_neem_oil")
            self.assertEqual(action["taskId"], f"neem_treatment:pest_recurring_programs:{plant['plantId']}:neem_cycle")
            self.assert_action_display_names(action, location_name="Atrium House")

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=FIXED_CONTEXT)
    def test_eval_keeps_multiple_programs_for_same_plant_distinct(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="loft", name="Loft", loc_type="room")
            plant = registry.add_plant(name="Hibiscus", location_id="loft", indoor_outdoor="indoor")
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
                            "suggestedAction": "apply_neem_oil",
                            "cadenceDays": [12, 15],
                            "activeMonths": [4, 5, 6, 7, 8, 9],
                        },
                        {
                            "programId": "soap_cycle",
                            "displayName": "Insecticidal soap",
                            "taskType": "soap_treatment",
                            "confirmEventType": "soap_confirmed",
                            "suggestedAction": "apply_insecticidal_soap",
                            "cadenceDays": [9, 12],
                            "activeMonths": [4, 5, 6, 7, 8, 9],
                        },
                    ],
                },
            )

            result = eval_engine.evaluate(dry_run=True)

            self.assertEqual(result["summary"]["totalActions"], 2)
            self.assertEqual(len({action["taskId"] for action in result["actions"]}), 2)
            for action in result["actions"]:
                self.assert_action_display_names(action, location_name="Loft")

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=FIXED_CONTEXT)
    def test_eval_repotting_uses_latest_anchor_and_preferred_window_for_due_at(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="sunroom", name="Sunroom", loc_type="room")
            plant = registry.add_plant(name="Rubber Tree", location_id="sunroom", indoor_outdoor="indoor")
            profiles.set_profile(
                "repotting",
                plant["plantId"],
                {
                    "repottingIntervalYears": [1, 2],
                    "bestMonths": [4, 5],
                    "lastRepottedAt": "2024-01-01",
                },
            )
            events.log_event(
                event_type="repotting_confirmed",
                plant_id=plant["plantId"],
                location_id="sunroom",
                effective_date="2025-01-10",
            )

            result = eval_engine.evaluate(dry_run=True)

            self.assertEqual(result["summary"]["totalActions"], 1)
            action = result["actions"][0]
            self.assertEqual(action["type"], "repotting_check")
            self.assertEqual(action["dueAt"], "2026-04-01T00:00:00+00:00")
            self.assert_action_display_names(action, location_name="Sunroom")

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=FIXED_CONTEXT)
    def test_eval_reads_scalar_maintenance_cadence(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="office", name="Office", loc_type="room")
            registry.add_microzone(microzone_id="desk_corner", location_id="office", name="Desk Corner")
            plant = registry.add_plant(
                name="Pothos",
                location_id="office",
                sublocation_id="desk_corner",
                indoor_outdoor="indoor",
            )
            profiles.set_profile(
                "maintenance",
                plant["plantId"],
                {"cleaningCadenceDays": 14},
            )

            result = eval_engine.evaluate(dry_run=True)

            self.assertEqual(result["summary"]["byType"]["maintenance_check"], 1)
            action = next(action for action in result["actions"] if action["type"] == "maintenance_check")
            self.assertEqual(action["dueAt"], FIXED_CONTEXT["evaluatedAt"])
            self.assert_action_display_names(action, location_name="Office", sublocation_name="Desk Corner")

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=FIXED_CONTEXT)
    def test_eval_reads_healthcheck_profiles(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="hall", name="Hall", loc_type="room")
            plant = registry.add_plant(name="Fern", location_id="hall", indoor_outdoor="indoor")
            profiles.set_profile(
                "healthcheck",
                plant["plantId"],
                {"checkCadenceDays": [7, 14]},
            )

            result = eval_engine.evaluate(dry_run=True)

            action = next(action for action in result["actions"] if action["type"] == "healthcheck_check")
            self.assertEqual(action["dueAt"], FIXED_CONTEXT["evaluatedAt"])
            self.assert_action_display_names(action, location_name="Hall")

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=JAN_CONTEXT)
    def test_eval_pruning_windows_support_wraparound_months(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="atrium", name="Atrium", loc_type="room")
            plant = registry.add_plant(name="Olive", location_id="atrium", indoor_outdoor="indoor")
            profiles.set_profile(
                "maintenance",
                plant["plantId"],
                {"pruningMonths": [11, 12, 1, 2]},
            )

            result = eval_engine.evaluate(dry_run=True)

            action = next(action for action in result["actions"] if action["type"] == "pruning_check")
            self.assertEqual(action["dueAt"], "2025-11-01T00:00:00+00:00")
            self.assert_action_display_names(action, location_name="Atrium")

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=FIXED_CONTEXT)
    def test_eval_status_reports_projected_open_tasks(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="winter_garden", name="Winter Garden", loc_type="room")
            plant = registry.add_plant(name="Rosemary", location_id="winter_garden")
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
                location_id="winter_garden",
            )
            task_id = f"watering_check:watering_profiles:{plant['plantId']}"
            reminders.open_task(
                task_id=task_id,
                task_type="watering_check",
                plant_id=plant["plantId"],
                location_id="winter_garden",
                reason="Old stale reminder",
                managed_by_rule_id="watering_profiles",
                confirm_event_type="watering_confirmed",
            )

            result = eval_engine.quick_status()

            self.assertEqual(result["openTasks"], 0)
            self.assertEqual(result["openTaskState"], [])

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=FIXED_CONTEXT)
    def test_eval_uses_effective_date_over_recorded_timestamp_for_recency(self, _mock_context):
        with plant_test_env() as data_dir:
            registry.add_location(location_id="study", name="Study", loc_type="room")
            plant = registry.add_plant(name="Basil", location_id="study")
            profiles.set_profile(
                "watering",
                plant["plantId"],
                {
                    "profileId": "watering:basil",
                    "baselineSource": "basil baseline",
                    "seasonalBaseline": {
                        "winter": {"level": "very_low", "baseIntervalDays": [14, 21]},
                        "spring": {"level": "medium", "baseIntervalDays": [6, 10]},
                        "summer": {"level": "high", "baseIntervalDays": [2, 4]},
                        "autumn": {"level": "low", "baseIntervalDays": [7, 10]},
                    },
                },
            )
            event = events.log_event(
                event_type="watering_confirmed",
                plant_id=plant["plantId"],
                location_id="study",
                effective_date="2026-03-30",
            )

            events_data = read_json(data_dir / "events.json")
            events_data["events"][0]["timestamp"] = "2026-03-01T09:00:00+00:00"
            write_json(data_dir / "events.json", events_data)

            result = eval_engine.evaluate(dry_run=True)

            self.assertEqual(result["summary"]["totalActions"], 0)
            self.assertIn(
                "Within baseline interval",
                result["noAction"][0]["reason"],
            )

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=FIXED_CONTEXT)
    def test_eval_prefers_newer_effective_date_over_later_backfilled_timestamp(self, _mock_context):
        with plant_test_env() as data_dir:
            registry.add_location(location_id="den", name="Den", loc_type="room")
            plant = registry.add_plant(name="Rosemary", location_id="den")
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
                location_id="den",
                effective_date="2026-03-30",
            )
            events.log_event(
                event_type="watering_confirmed",
                plant_id=plant["plantId"],
                location_id="den",
                effective_date="2026-03-01",
            )

            events_data = read_json(data_dir / "events.json")
            events_data["events"][0]["timestamp"] = "2026-03-10T09:00:00+00:00"
            events_data["events"][1]["timestamp"] = "2026-03-31T09:00:00+00:00"
            write_json(data_dir / "events.json", events_data)

            latest_event = events.get_last_event(
                plant["plantId"],
                event_type="watering_confirmed",
                tz_name="UTC",
            )
            result = eval_engine.evaluate(dry_run=True)

            self.assertEqual(latest_event["effectiveDateLocal"], "2026-03-30")
            self.assertEqual(result["summary"]["totalActions"], 0)


if __name__ == "__main__":
    unittest.main()
