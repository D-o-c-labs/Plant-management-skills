import unittest

from test_support import plant_test_env

from plant_mgmt import events, profiles, registry


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


if __name__ == "__main__":
    unittest.main()
