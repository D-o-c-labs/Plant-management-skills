import unittest
from unittest.mock import patch

from test_support import plant_test_env

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

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=FIXED_CONTEXT)
    def test_eval_reads_scalar_maintenance_cadence(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="office", name="Office", loc_type="room")
            plant = registry.add_plant(name="Pothos", location_id="office", indoor_outdoor="indoor")
            profiles.set_profile(
                "maintenance",
                plant["plantId"],
                {"cleaningCadenceDays": 14},
            )

            result = eval_engine.evaluate(dry_run=True)

            self.assertEqual(result["summary"]["byType"]["maintenance_check"], 1)
            action = next(action for action in result["actions"] if action["type"] == "maintenance_check")
            self.assertEqual(action["dueAt"], FIXED_CONTEXT["evaluatedAt"])

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


if __name__ == "__main__":
    unittest.main()
