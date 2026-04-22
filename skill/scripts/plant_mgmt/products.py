"""Product inventory CRUD operations."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import config, store


PRODUCT_CATEGORIES = {
    "pesticide",
    "fungicide",
    "fertilizer",
    "soil_amendment",
    "substrate",
    "tool",
    "other",
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _mint_product_id(data):
    numeric_id = data["nextProductNumericId"]
    return f"product_{numeric_id:03d}", numeric_id + 1


def _normalise_target_issues(target_issues):
    if target_issues is None:
        return []
    if isinstance(target_issues, str):
        target_issues = target_issues.split(",")
    return [issue.strip() for issue in target_issues if issue and issue.strip()]


def _validate_category(category):
    if category not in PRODUCT_CATEGORIES:
        raise ValueError(f"Invalid product category: {category}")


def _copy_photo(product_id, photo_file):
    if not photo_file:
        return None

    source = Path(photo_file).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Product photo not found: {source}")

    suffix = source.suffix.lower() or ".jpg"
    relative_path = Path("media") / "products" / f"{product_id}{suffix}"
    destination = config.get_data_dir() / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return relative_path.as_posix()


def list_products(*, category=None, target_issue=None, as_json=False):
    """List products, optionally filtered by category and/or target issue."""
    data = store.read("products.json")
    products = data["products"]
    if category:
        products = [product for product in products if product["category"] == category]
    if target_issue:
        products = [
            product
            for product in products
            if target_issue in product.get("targetIssues", [])
        ]
    return products


def get_product(product_id):
    """Get a single product by ID. Returns None if not found."""
    data = store.read("products.json")
    for product in data["products"]:
        if product["productId"] == product_id:
            return product
    return None


def add_product(
    *,
    display_name,
    category,
    description,
    target_issues=None,
    photo_file=None,
    notes=None,
):
    """Add a new inventory product. Returns the created product."""
    _validate_category(category)
    data = store.read("products.json")
    product_id, next_numeric_id = _mint_product_id(data)
    photo_path = _copy_photo(product_id, photo_file)

    product = {
        "productId": product_id,
        "displayName": display_name,
        "category": category,
        "description": description,
        "targetIssues": _normalise_target_issues(target_issues),
        "photoPath": photo_path,
        "notes": notes,
        "addedAt": _now_iso(),
    }

    data["products"].append(product)
    data["nextProductNumericId"] = next_numeric_id
    store.write("products.json", data)
    return product


def update_product(product_id, **fields):
    """Partially update a product. Returns the updated product."""
    data = store.read("products.json")
    for index, product in enumerate(data["products"]):
        if product["productId"] != product_id:
            continue

        updates = {key: value for key, value in fields.items() if value is not None}
        if "category" in updates:
            _validate_category(updates["category"])
        if "targetIssues" in updates:
            updates["targetIssues"] = _normalise_target_issues(updates["targetIssues"])
        if "photoFile" in updates:
            updates["photoPath"] = _copy_photo(product_id, updates.pop("photoFile"))

        data["products"][index] = {**product, **updates}
        store.write("products.json", data)
        return data["products"][index]

    raise ValueError(f"Product not found: {product_id}")


def remove_product(product_id):
    """Hard-delete a product and its copied photo, if present."""
    data = store.read("products.json")
    for index, product in enumerate(data["products"]):
        if product["productId"] != product_id:
            continue

        removed = data["products"].pop(index)
        store.write("products.json", data)

        photo_path = removed.get("photoPath")
        if photo_path:
            absolute_photo_path = config.get_data_dir() / photo_path
            if absolute_photo_path.exists() and absolute_photo_path.is_file():
                absolute_photo_path.unlink()

        return removed

    raise ValueError(f"Product not found: {product_id}")


def cli_products(args):
    as_json = getattr(args, "json", False)
    subcmd = args.subcmd

    if subcmd == "list":
        products = list_products(
            category=getattr(args, "category", None),
            target_issue=getattr(args, "target_issue", None),
        )
        if as_json:
            print(json.dumps(products, indent=2, ensure_ascii=False))
        else:
            if not products:
                print("No products found.")
                return
            for product in products:
                issues = ",".join(product.get("targetIssues", [])) or "-"
                print(
                    f"  {product['productId']:<12} "
                    f"{product['category']:<15} "
                    f"{product['displayName']:<30} "
                    f"{issues}"
                )
            print(f"\n{len(products)} product(s)")

    elif subcmd == "get":
        product = get_product(args.productId)
        if product:
            print(json.dumps(product, indent=2, ensure_ascii=False))
        else:
            print(f"Product not found: {args.productId}")

    elif subcmd == "add":
        product = add_product(
            display_name=args.display_name,
            category=args.category,
            description=args.description,
            target_issues=getattr(args, "target_issues", None),
            photo_file=getattr(args, "photo_file", None),
            notes=getattr(args, "notes", None),
        )
        if as_json:
            print(json.dumps(product, indent=2, ensure_ascii=False))
        else:
            print(f"Created: {product['productId']} ({product['displayName']})")

    elif subcmd == "update":
        updates = {}
        if getattr(args, "data", None):
            updates.update(json.loads(args.data))
        for attr, field in (
            ("display_name", "displayName"),
            ("category", "category"),
            ("description", "description"),
            ("target_issues", "targetIssues"),
            ("photo_file", "photoFile"),
            ("notes", "notes"),
        ):
            value = getattr(args, attr, None)
            if value is not None:
                updates[field] = value
        product = update_product(args.productId, **updates)
        if as_json:
            print(json.dumps(product, indent=2, ensure_ascii=False))
        else:
            print(f"Updated: {product['productId']}")

    elif subcmd == "remove":
        product = remove_product(args.productId)
        if as_json:
            print(json.dumps(product, indent=2, ensure_ascii=False))
        else:
            print(f"Removed: {product['productId']}")

    else:
        print("Usage: plant_mgmt products {list|get|add|update|remove}")
