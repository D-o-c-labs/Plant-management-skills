import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime

from test_support import plant_test_env, read_json

from plant_mgmt import products
from plant_mgmt_cli import build_parser


class ProductsTest(unittest.TestCase):
    def test_add_product_with_required_fields_mints_id_and_defaults(self):
        with plant_test_env():
            product = products.add_product(
                display_name="Olio di neem BioGarden",
                category="pesticide",
                description="Olio di neem puro 100%.",
            )

            self.assertEqual(product["productId"], "product_001")
            self.assertEqual(product["targetIssues"], [])
            self.assertIsNone(product["photoPath"])
            self.assertIsNone(product["notes"])
            datetime.fromisoformat(product["addedAt"])

    def test_add_product_with_photo_copies_to_media_products(self):
        with plant_test_env() as data_dir:
            source = data_dir / "source.jpg"
            source.write_bytes(b"fake image")

            product = products.add_product(
                display_name="Neem",
                category="pesticide",
                description="Neem oil.",
                photo_file=str(source),
            )

            self.assertEqual(product["photoPath"], "media/products/product_001.jpg")
            self.assertEqual((data_dir / product["photoPath"]).read_bytes(), b"fake image")

    def test_list_products_filters_by_target_issue(self):
        with plant_test_env():
            products.add_product(
                display_name="Neem",
                category="pesticide",
                description="For mites.",
                target_issues=["spider_mites"],
            )
            products.add_product(
                display_name="Fertilizer",
                category="fertilizer",
                description="General feeding.",
                target_issues=["nitrogen_deficiency"],
            )

            matches = products.list_products(target_issue="spider_mites")

            self.assertEqual([product["displayName"] for product in matches], ["Neem"])

    def test_list_products_filters_by_category(self):
        with plant_test_env():
            products.add_product(
                display_name="Neem",
                category="pesticide",
                description="For mites.",
            )
            products.add_product(
                display_name="Fertilizer",
                category="fertilizer",
                description="General feeding.",
            )

            matches = products.list_products(category="pesticide")

            self.assertEqual([product["displayName"] for product in matches], ["Neem"])

    def test_update_product_partial_preserves_unchanged_fields(self):
        with plant_test_env():
            original = products.add_product(
                display_name="Neem",
                category="pesticide",
                description="For mites.",
                target_issues=["spider_mites"],
            )

            updated = products.update_product(original["productId"], notes="Use in evening.")

            self.assertEqual(updated["displayName"], "Neem")
            self.assertEqual(updated["targetIssues"], ["spider_mites"])
            self.assertEqual(updated["notes"], "Use in evening.")

    def test_remove_product_deletes_record_and_photo(self):
        with plant_test_env() as data_dir:
            source = data_dir / "source.jpg"
            source.write_bytes(b"fake image")
            product = products.add_product(
                display_name="Neem",
                category="pesticide",
                description="Neem oil.",
                photo_file=str(source),
            )
            copied_photo = data_dir / product["photoPath"]

            removed = products.remove_product(product["productId"])

            self.assertEqual(removed["productId"], "product_001")
            self.assertFalse(copied_photo.exists())
            self.assertEqual(products.list_products(), [])

    def test_invalid_category_raises_schema_validation_error(self):
        with plant_test_env():
            with self.assertRaises(ValueError):
                products.add_product(
                    display_name="Mystery",
                    category="magic",
                    description="Invalid category.",
                )

    def test_two_adds_increment_next_product_id(self):
        with plant_test_env() as data_dir:
            first = products.add_product(
                display_name="Neem",
                category="pesticide",
                description="Neem oil.",
            )
            second = products.add_product(
                display_name="Soap",
                category="pesticide",
                description="Insecticidal soap.",
            )

            data = read_json(data_dir / "products.json")
            self.assertEqual(first["productId"], "product_001")
            self.assertEqual(second["productId"], "product_002")
            self.assertEqual(data["nextProductNumericId"], 3)

    def test_cli_accepts_comma_separated_target_issues(self):
        with plant_test_env():
            parser = build_parser()
            args = parser.parse_args(
                [
                    "products",
                    "add",
                    "--display-name",
                    "Neem",
                    "--category",
                    "pesticide",
                    "--description",
                    "Neem oil.",
                    "--target-issues",
                    "spider_mites,aphids",
                ]
            )

            with redirect_stdout(io.StringIO()):
                args.func(args)

            product = products.get_product("product_001")
            self.assertEqual(product["targetIssues"], ["spider_mites", "aphids"])


if __name__ == "__main__":
    unittest.main()
