import unittest
from datetime import datetime
from unittest.mock import patch

from test_support import plant_test_env, read_json

from plant_mgmt import eval_engine, events, profiles, registry, store


APRIL_CONTEXT = {
    "evaluatedAt": "2026-04-22T09:00:00+00:00",
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

RAIN_CONTEXT = {
    **APRIL_CONTEXT,
    "weatherProvided": True,
    "weather": {"condition": "rain"},
}

JANUARY_CONTEXT = {
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


def _write_system(system_id="drip_line", **updates):
    system = {
        "irrigationSystemId": system_id,
        "locationId": "balcony",
        "enabled": True,
        "controlMode": "backend_controlled",
        "runoffRisk": "low",
        "manualExceptionPlantIds": [],
        "autoSchedule": {"cadenceDays": 3},
        "notes": "",
    }
    system.update(updates)
    store.write(
        "irrigation_systems.json",
        {"version": 1, "irrigationSystems": [system]},
    )
    return system


def _add_auto_plant(name="Basil", *, system_id="drip_line"):
    return registry.add_plant(
        name=name,
        location_id="balcony",
        irrigation_mode="automatic",
        irrigation_system_id=system_id,
        attached_to_irrigation=True,
    )


def _set_watering_profile(plant_id, interval=3):
    profiles.set_profile(
        "watering",
        plant_id,
        {
            "baselineSource": "test profile",
            "seasonalBaseline": {
                "winter": {"level": "low", "baseIntervalDays": [interval, interval]},
                "spring": {"level": "low", "baseIntervalDays": [interval, interval]},
                "summer": {"level": "low", "baseIntervalDays": [interval, interval]},
                "autumn": {"level": "low", "baseIntervalDays": [interval, interval]},
            },
        },
    )


def _log_auto_event(plant_id, system_id, effective_date):
    return events.log_event(
        event_type="watering_confirmed",
        source="auto_irrigation",
        plant_id=plant_id,
        scope=f"auto_irrigation:{system_id}",
        details={"irrigationSystemId": system_id, "auto": True},
        effective_date=effective_date,
    )


class AutoIrrigationTest(unittest.TestCase):
    @patch("plant_mgmt.eval_engine.get_current_context", return_value=APRIL_CONTEXT)
    def test_auto_schedule_backfills_from_last_auto_event(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            _write_system(autoSchedule={"cadenceDays": 3})
            plant = _add_auto_plant()
            _log_auto_event(plant["plantId"], "drip_line", "2026-04-15")

            result = eval_engine.evaluate(dry_run=False)

            emitted = result["autoIrrigation"]["emittedEvents"]
            self.assertEqual([event["effectiveDateLocal"] for event in emitted], ["2026-04-18", "2026-04-21"])
            self.assertTrue(all(event["eventId"] for event in emitted))
            event_dates = [
                event["effectiveDateLocal"]
                for event in events.list_events(event_type="watering_confirmed", limit=0)
                if (event.get("details") or {}).get("auto") is True
            ]
            self.assertIn("2026-04-18", event_dates)
            self.assertIn("2026-04-21", event_dates)

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=APRIL_CONTEXT)
    def test_disabled_system_does_not_emit(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            _write_system(enabled=False, autoSchedule={"cadenceDays": 3})
            _add_auto_plant()

            result = eval_engine.evaluate(dry_run=False)

            self.assertEqual(result["autoIrrigation"]["emittedEvents"], [])
            self.assertIn(
                {"systemId": "drip_line", "reason": "enabled=false"},
                result["autoIrrigation"]["skippedSystems"],
            )

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=JANUARY_CONTEXT)
    def test_disabled_season_does_not_emit(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            _write_system(
                autoSchedule={
                    "cadenceDays": 1,
                    "seasonalSchedule": {"winter": {"enabled": False}},
                }
            )
            plant = _add_auto_plant()
            _log_auto_event(plant["plantId"], "drip_line", "2026-01-12")

            result = eval_engine.evaluate(dry_run=False)

            self.assertEqual(result["autoIrrigation"]["emittedEvents"], [])
            self.assertTrue(
                all(skip["reason"] == "season_disabled" for skip in result["autoIrrigation"]["skippedSystems"])
            )

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=RAIN_CONTEXT)
    def test_skip_on_rain_skips_today_but_backfills_past_dates(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            _write_system(autoSchedule={"cadenceDays": 3, "skipOnRain": True})
            plant = _add_auto_plant()
            _log_auto_event(plant["plantId"], "drip_line", "2026-04-16")

            result = eval_engine.evaluate(dry_run=False)

            emitted = result["autoIrrigation"]["emittedEvents"]
            self.assertEqual([event["effectiveDateLocal"] for event in emitted], ["2026-04-19"])
            self.assertIn(
                {"systemId": "drip_line", "reason": "weather_rain", "date": "2026-04-22"},
                result["autoIrrigation"]["skippedSystems"],
            )

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=APRIL_CONTEXT)
    def test_manual_exception_plant_is_excluded(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            _write_system(autoSchedule={"cadenceDays": 3})
            included = _add_auto_plant("Included")
            excluded = _add_auto_plant("Excluded")
            registry.update_irrigation_system(
                "drip_line",
                {"manualExceptionPlantIds": [excluded["plantId"]]},
            )
            _log_auto_event(included["plantId"], "drip_line", "2026-04-19")

            result = eval_engine.evaluate(dry_run=False)

            emitted_event_id = result["autoIrrigation"]["emittedEvents"][0]["eventId"]
            event = next(event for event in events.list_events(limit=0) if event["eventId"] == emitted_event_id)
            self.assertEqual(event["plantIds"], [included["plantId"]])

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=APRIL_CONTEXT)
    def test_dry_run_reports_without_writing_events(self, _mock_context):
        with plant_test_env() as data_dir:
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            _write_system(autoSchedule={"cadenceDays": 3})
            plant = _add_auto_plant()
            _log_auto_event(plant["plantId"], "drip_line", "2026-04-19")
            before = read_json(data_dir / "events.json")

            result = eval_engine.evaluate(dry_run=True)

            self.assertEqual(result["autoIrrigation"]["emittedEvents"][0]["eventId"], None)
            self.assertEqual(read_json(data_dir / "events.json"), before)

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=APRIL_CONTEXT)
    def test_watering_rule_is_silenced_by_auto_event_prepass(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            _write_system(autoSchedule={"cadenceDays": 3})
            plant = _add_auto_plant()
            _set_watering_profile(plant["plantId"], interval=3)
            _log_auto_event(plant["plantId"], "drip_line", "2026-04-19")

            result = eval_engine.evaluate(dry_run=False)

            self.assertEqual(result["autoIrrigation"]["backfilledDates"], ["2026-04-22"])
            self.assertFalse(
                any(action["type"] == "watering_check" for action in result["actions"])
            )

    @patch("plant_mgmt.eval_engine.get_current_context", return_value=APRIL_CONTEXT)
    def test_backfill_is_capped_at_thirty_days(self, _mock_context):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            _write_system(autoSchedule={"cadenceDays": 3})
            plant = _add_auto_plant()
            _log_auto_event(plant["plantId"], "drip_line", "2026-02-21")

            result = eval_engine.evaluate(dry_run=True)

            dates = result["autoIrrigation"]["backfilledDates"]
            self.assertEqual(dates[0], "2026-03-23")
            self.assertEqual(dates[-1], "2026-04-22")
            first_date = datetime.fromisoformat(dates[0]).date()
            eval_date = datetime.fromisoformat(APRIL_CONTEXT["evaluatedAt"]).date()
            self.assertLessEqual((eval_date - first_date).days, 30)


if __name__ == "__main__":
    unittest.main()
