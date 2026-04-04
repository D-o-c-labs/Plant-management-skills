import json
import io
import unittest
from contextlib import redirect_stdout

from test_support import plant_test_env

from plant_mgmt import events, profiles, registry
from plant_mgmt_cli import build_parser


class EventsTest(unittest.TestCase):
    def test_logging_repotting_event_updates_profile_anchor(self):
        with plant_test_env():
            registry.add_location(location_id="garden_room", name="Garden Room", loc_type="room")
            plant = registry.add_plant(name="Monstera", location_id="garden_room", indoor_outdoor="indoor")
            profiles.set_profile(
                "repotting",
                plant["plantId"],
                {
                    "profileId": "repot:monstera",
                    "repottingIntervalYears": [1, 2],
                    "bestMonths": [3, 4, 5],
                },
            )

            events.log_event(
                event_type="repotting_confirmed",
                plant_id=plant["plantId"],
                location_id="garden_room",
                effective_date="2026-03-20",
            )

            profile = profiles.get_profile("repotting", "repot:monstera")
            self.assertEqual(profile["lastRepottedAt"], "2026-03-20")

    def test_log_event_supports_exact_effective_datetime(self):
        with plant_test_env():
            registry.add_location(location_id="kitchen", name="Kitchen", loc_type="room")
            plant = registry.add_plant(name="Mint", location_id="kitchen", indoor_outdoor="indoor")

            event = events.log_event(
                event_type="watering_confirmed",
                plant_id=plant["plantId"],
                location_id="kitchen",
                effective_datetime="2026-03-18T07:30:00",
                effective_precision="exact",
            )

            self.assertEqual(event["effectiveDateLocal"], "2026-03-18")
            self.assertEqual(event["effectiveDateTimeLocal"], "2026-03-18T07:30:00")
            self.assertEqual(event["effectivePrecision"], "exact")

    def test_events_cli_exposes_effective_time_flags(self):
        with plant_test_env():
            registry.add_location(location_id="office", name="Office", loc_type="room")
            plant = registry.add_plant(name="Basil", location_id="office", indoor_outdoor="indoor")

            parser = build_parser()
            args = parser.parse_args(
                [
                    "--json",
                    "events",
                    "log",
                    "--type",
                    "watering_confirmed",
                    "--plant",
                    plant["plantId"],
                    "--location",
                    "office",
                    "--effective-datetime",
                    "2026-03-18T07:30:00",
                    "--effective-precision",
                    "exact",
                ]
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                args.func(args)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["effectiveDateLocal"], "2026-03-18")
            self.assertEqual(payload["effectiveDateTimeLocal"], "2026-03-18T07:30:00")
            self.assertEqual(payload["effectivePrecision"], "exact")


if __name__ == "__main__":
    unittest.main()
