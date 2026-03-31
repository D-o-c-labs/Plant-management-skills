import unittest

from skills.scripts.plant_mgmt import profiles
from skills.scripts.tests.test_support import plant_test_env, read_json

from skills.scripts.plant_mgmt import registry


class ProfilesTest(unittest.TestCase):
    def test_set_profile_links_custom_profile_id_to_plant(self):
        with plant_test_env() as data_dir:
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            plant = registry.add_plant(name="Basil", location_id="balcony")

            profile = profiles.set_profile(
                "watering",
                plant["plantId"],
                {
                    "profileId": "watering:basil",
                    "baselineSource": "herb baseline",
                    "seasonalBaseline": {
                        "winter": {"level": "very_low", "baseIntervalDays": [14, 21]},
                        "spring": {"level": "medium", "baseIntervalDays": [4, 7]},
                        "summer": {"level": "high", "baseIntervalDays": [2, 4]},
                        "autumn": {"level": "low", "baseIntervalDays": [7, 10]},
                    },
                },
            )

            self.assertEqual(profile["profileId"], "watering:basil")
            self.assertEqual(profiles.get_profile("watering", "watering:basil")["plantId"], plant["plantId"])

            plants_data = read_json(data_dir / "plants.json")
            self.assertEqual(plants_data["plants"][0]["wateringProfileId"], "watering:basil")

    def test_remove_profile_clears_denormalized_plant_reference(self):
        with plant_test_env() as data_dir:
            registry.add_location(location_id="living", name="Living", loc_type="room")
            plant = registry.add_plant(name="Monstera", location_id="living", indoor_outdoor="indoor")
            profiles.set_profile(
                "fertilization",
                plant["plantId"],
                {"profileId": "fert:monstera", "activeMonths": [3, 4, 5], "cadenceDays": [20, 30]},
            )

            removed = profiles.remove_profile("fertilization", "fert:monstera")
            self.assertTrue(removed)

            plants_data = read_json(data_dir / "plants.json")
            self.assertIsNone(plants_data["plants"][0]["fertilizationProfileId"])


if __name__ == "__main__":
    unittest.main()

