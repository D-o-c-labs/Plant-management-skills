import json
import unittest
from unittest.mock import patch

from test_support import plant_test_env, read_json

from plant_mgmt import lookup


class LookupTest(unittest.TestCase):
    def test_search_ignores_negative_cache_and_scrubs_it_on_success(self):
        with plant_test_env() as data_dir:
            cache_path = data_dir / "lookup_cache.json"
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "search:basil": {
                            "query": "basil",
                            "found": False,
                            "source": None,
                            "species": None,
                            "care": None,
                        }
                    },
                    handle,
                )

            with patch("plant_mgmt.lookup.config.get_configured_apis", return_value={"trefle": {"api_key": "token"}}):
                with patch(
                    "plant_mgmt.lookup._trefle_search",
                    return_value=lookup._species_result("basil", "trefle", common_name="Basil"),
                ):
                    result = lookup.search("basil")

            self.assertTrue(result["found"])
            cache = read_json(cache_path)
            self.assertTrue(cache["search:basil"]["found"])


if __name__ == "__main__":
    unittest.main()
