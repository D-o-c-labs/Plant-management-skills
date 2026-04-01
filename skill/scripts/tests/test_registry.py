import unittest

from test_support import plant_test_env

from plant_mgmt import registry, store


class RegistryTest(unittest.TestCase):
    def test_update_plant_recomputes_irrigation_effective_state(self):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            store.write(
                "irrigation_systems.json",
                {
                    "version": 1,
                    "irrigationSystems": [
                        {
                            "irrigationSystemId": "drip_line",
                            "locationId": "balcony",
                            "enabled": False,
                            "controlMode": "backend_controlled",
                            "runoffRisk": "low",
                            "notes": "",
                        }
                    ],
                },
            )
            plant = registry.add_plant(
                name="Basil",
                location_id="balcony",
                irrigation_mode="automatic",
                irrigation_system_id="drip_line",
                attached_to_irrigation=True,
            )
            self.assertEqual(plant["irrigationEffectiveState"], "attached_but_system_off")

            updated = registry.update_plant(plant["plantId"], {"irrigationMode": "manual", "attachedToIrrigation": False})

            self.assertEqual(updated["irrigationEffectiveState"], "manual_only")

    def test_update_irrigation_system_propagates_to_attached_plants(self):
        with plant_test_env():
            registry.add_location(location_id="balcony", name="Balcony", loc_type="balcony")
            store.write(
                "irrigation_systems.json",
                {
                    "version": 1,
                    "irrigationSystems": [
                        {
                            "irrigationSystemId": "drip_line",
                            "locationId": "balcony",
                            "enabled": False,
                            "controlMode": "backend_controlled",
                            "runoffRisk": "low",
                            "notes": "",
                        }
                    ],
                },
            )
            plant = registry.add_plant(
                name="Tomato",
                location_id="balcony",
                irrigation_mode="automatic",
                irrigation_system_id="drip_line",
                attached_to_irrigation=True,
            )

            registry.update_irrigation_system("drip_line", {"enabled": True})

            refreshed = registry.get_plant(plant["plantId"])
            self.assertEqual(refreshed["irrigationEffectiveState"], "active")


if __name__ == "__main__":
    unittest.main()
