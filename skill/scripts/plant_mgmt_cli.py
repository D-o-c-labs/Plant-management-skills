#!/usr/bin/env python3
"""Plant Management Skill — CLI entry point.

Usage: python3 scripts/plant_mgmt_cli.py <command> [subcommand] [options]

Environment:
    PLANT_DATA_DIR   (required) Path to plant data directory
    PLANT_SKILL_DIR  (optional) Path to skill root (auto-detected)
    PLANT_TIMEZONE   (optional) Timezone override, e.g. Europe/Rome
    PLANT_LOCALE     (optional) Locale hint, e.g. it, en
"""

import argparse
import json
import sys
import os

# Ensure the scripts directory is on the path so plant_mgmt is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from plant_mgmt import config, init as init_mod, schemas, store
except ModuleNotFoundError as exc:
    if exc.name in {"jsonschema", "requests"}:
        print(
            "Missing Python dependency. Install packages from scripts/requirements.txt "
            "in the host Python environment before using this skill.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    raise


def _print_json(data):
    """Print data as formatted JSON to stdout."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _print_result(data, as_json=False):
    """Print result as JSON or human-readable text."""
    if as_json:
        _print_json(data)
    else:
        # Simple human-readable formatting
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list):
                    if value:
                        print(f"{key}:")
                        for item in value:
                            if isinstance(item, dict):
                                print(f"  - {json.dumps(item, ensure_ascii=False)}")
                            else:
                                print(f"  - {item}")
                    else:
                        print(f"{key}: (none)")
                elif isinstance(value, dict):
                    print(f"{key}:")
                    for k, v in value.items():
                        print(f"  {k}: {v}")
                else:
                    print(f"{key}: {value}")
        else:
            print(data)


# ---------------------------------------------------------------------------
# Command: init
# ---------------------------------------------------------------------------
def cmd_init(args):
    """Initialize the data directory from seed templates."""
    if getattr(args, "from_existing", None):
        result = init_mod.migrate_from_existing(args.from_existing)
    else:
        result = init_mod.init_data_dir(force=args.force)
    if not args.json:
        created = len(result.get("created", []))
        imported = len(result.get("imported", []))
        skipped = len(result.get("skipped", []))
        initialized = len(result.get("initialized", []))
        warnings = len(result.get("validation_warnings", []))
        errors = len(result["errors"])
        print(f"Data directory: {config.get_data_dir()}")
        if created:
            print(f"Created {created} file(s): {', '.join(result['created'])}")
        if imported:
            print(f"Imported {imported} file(s): {', '.join(result['imported'])}")
        if skipped:
            print(f"Skipped {skipped} file(s) (already exist): {', '.join(result['skipped'])}")
        if initialized:
            print(f"Initialized {initialized} missing file(s) from seeds: {', '.join(result['initialized'])}")
        if warnings:
            print(f"Validation warnings ({warnings}):")
            for warning in result["validation_warnings"]:
                print(f"  {warning['file']}:")
                for msg in warning["warnings"][:3]:
                    print(f"    - {msg}")
        if errors:
            print(f"Errors ({errors}):")
            for e in result["errors"]:
                print(f"  - {e}")
            sys.exit(1)
        if not errors:
            print("Data directory ready.")
    else:
        _print_json(result)


# ---------------------------------------------------------------------------
# Command: validate
# ---------------------------------------------------------------------------
def cmd_validate(args):
    """Validate all JSON data files against their schemas."""
    results = store.validate_all()

    if args.json:
        _print_json(results)
        return

    all_valid = True
    for filename, errors in sorted(results.items()):
        if errors:
            all_valid = False
            print(f"FAIL  {filename}")
            for e in errors:
                print(f"      {e}")
        else:
            print(f"OK    {filename}")

    if all_valid:
        print(f"\nAll {len(results)} file(s) valid.")
    else:
        print(f"\nValidation errors found.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command: check
# ---------------------------------------------------------------------------
def cmd_check(args):
    """Check the health of the data directory."""
    result = init_mod.check_data_dir()
    if args.json:
        _print_json(result)
        return

    print(f"Data directory: {result['data_dir']}")
    print(f"Exists: {result['exists']}")
    if result["present"]:
        print(f"Present ({len(result['present'])}): {', '.join(result['present'])}")
    if result["missing"]:
        print(f"Missing ({len(result['missing'])}): {', '.join(result['missing'])}")

    if result.get("validation"):
        has_errors = any(v for v in result["validation"].values())
        if has_errors:
            print("\nValidation issues:")
            for filename, errors in result["validation"].items():
                if errors:
                    print(f"  {filename}:")
                    for e in errors:
                        print(f"    - {e}")
        else:
            print("\nAll present files pass validation.")


# ---------------------------------------------------------------------------
# Command: migrate
# ---------------------------------------------------------------------------
def cmd_migrate(args):
    """Migrate data from an existing directory."""
    result = init_mod.migrate_from_existing(args.source)

    if args.json:
        _print_json(result)
        return

    imported = len(result["imported"])
    initialized = len(result.get("initialized", []))
    warnings = len(result.get("validation_warnings", []))
    errors = len(result["errors"])

    print(f"Source: {args.source}")
    print(f"Target: {config.get_data_dir()}")
    if imported:
        print(f"Imported {imported} item(s): {', '.join(result['imported'])}")
    if initialized:
        print(f"Initialized {initialized} missing item(s): {', '.join(result['initialized'])}")
    if warnings:
        print(f"\nValidation warnings ({warnings}):")
        for w in result["validation_warnings"]:
            print(f"  {w['file']}:")
            for msg in w["warnings"][:3]:
                print(f"    - {msg}")
    if errors:
        print(f"\nErrors ({errors}):")
        for e in result["errors"]:
            print(f"  - {e}")
        sys.exit(1)

    if not errors:
        print("\nMigration complete.")


# ---------------------------------------------------------------------------
# Command stubs for Phase 2+ (plants, locations, microzones, irrigation, etc.)
# ---------------------------------------------------------------------------
def cmd_plants(args):
    """Plant registry operations."""
    from plant_mgmt import registry
    registry.cli_plants(args)


def cmd_locations(args):
    """Location operations."""
    from plant_mgmt import registry
    registry.cli_locations(args)


def cmd_microzones(args):
    """Microzone operations."""
    from plant_mgmt import registry
    registry.cli_microzones(args)


def cmd_irrigation(args):
    """Irrigation system operations."""
    from plant_mgmt import registry
    registry.cli_irrigation(args)


def cmd_profiles(args):
    """Profile operations."""
    from plant_mgmt import profiles
    profiles.cli_profiles(args)


def cmd_events(args):
    """Event operations."""
    from plant_mgmt import events
    events.cli_events(args)


def cmd_products(args):
    """Product inventory operations."""
    from plant_mgmt import products
    products.cli_products(args)


def cmd_reminders(args):
    """Reminder operations."""
    from plant_mgmt import reminders
    reminders.cli_reminders(args)


def cmd_eval(args):
    """Run care evaluation."""
    from plant_mgmt import eval_engine, render

    if args.subcmd == "render":
        payload_raw = sys.stdin.read()
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError as exc:
            raise ValueError("eval render expects JSON on stdin with an 'actions' array.") from exc

        if not isinstance(payload, dict) or "actions" not in payload:
            raise ValueError("eval render expects JSON on stdin with an 'actions' array.")
        if not isinstance(payload["actions"], list):
            raise ValueError("eval render expects 'actions' to be a JSON array.")

        locale = render.normalize_locale(config.load_config().get("locale"))
        message = render.render_message(
            payload["actions"],
            locale=locale,
            auto_irrigation=payload.get("autoIrrigation"),
        )

        if getattr(args, "json", False):
            print(json.dumps({"message": message}, ensure_ascii=False))
        elif message is not None:
            print(message)
        return

    eval_engine.cli_eval(args)


def cmd_lookup(args):
    """External API lookups."""
    from plant_mgmt import lookup
    lookup.cli_lookup(args)


def _add_effective_time_arguments(parser):
    """Add effective-time flags shared by event logging and reminder confirmations."""
    parser.add_argument("--effective-date", help="Effective local date (YYYY-MM-DD)")
    parser.add_argument("--effective-datetime", help="Effective local datetime (ISO 8601)")
    parser.add_argument(
        "--effective-precision",
        choices=["day", "part_of_day", "hour", "exact"],
        default="day",
        help="Precision of the effective event time",
    )
    parser.add_argument(
        "--effective-part-of-day",
        choices=["morning", "afternoon", "evening", "night"],
        help="Part of day when precision is part_of_day",
    )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="plant_mgmt",
        description="Plant Management Skill — CLI for plant data, care evaluation, and lookups.",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p_init = sub.add_parser("init", help="Initialize data directory from seed templates")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing files")
    p_init.add_argument("--from-existing", help="Import from an existing data directory instead of only copying seeds")
    p_init.set_defaults(func=cmd_init)

    # validate
    p_val = sub.add_parser("validate", help="Validate all data files against schemas")
    p_val.set_defaults(func=cmd_validate)

    # check
    p_check = sub.add_parser("check", help="Check data directory health")
    p_check.set_defaults(func=cmd_check)

    # migrate
    p_mig = sub.add_parser("migrate", help="Migrate from existing data directory")
    p_mig.add_argument("source", help="Path to source data directory")
    p_mig.set_defaults(func=cmd_migrate)

    # plants
    p_plants = sub.add_parser("plants", help="Plant registry operations")
    plants_sub = p_plants.add_subparsers(dest="subcmd")
    p_pl_list = plants_sub.add_parser("list", help="List plants")
    p_pl_list.add_argument("--status", help="Filter by status")
    p_pl_list.add_argument("--location", help="Filter by locationId")
    p_pl_get = plants_sub.add_parser("get", help="Get plant details")
    p_pl_get.add_argument("plantId", help="Plant ID")
    p_pl_add = plants_sub.add_parser("add", help="Add a new plant")
    p_pl_add.add_argument("--name", required=True, help="Display name")
    p_pl_add.add_argument("--location", required=True, help="Location ID")
    p_pl_add.add_argument("--sublocation", help="Microzone ID")
    p_pl_add.add_argument("--species", help="Common species name")
    p_pl_add.add_argument("--scientific-name", help="Scientific species name")
    p_pl_add.add_argument("--indoor-outdoor", choices=["indoor", "outdoor"], default="outdoor")
    p_pl_add.add_argument("--irrigation-mode", choices=["manual", "automatic", "mixed"], default="manual")
    p_pl_add.add_argument("--irrigation-system", help="Irrigation system ID")
    p_pl_add.add_argument("--attached-to-irrigation", action="store_true")
    p_pl_add.add_argument("--notes", help="Notes")
    p_pl_update = plants_sub.add_parser("update", help="Update plant fields")
    p_pl_update.add_argument("plantId", help="Plant ID")
    p_pl_update.add_argument("--data", required=True, help="JSON object with fields to update")
    p_pl_archive = plants_sub.add_parser("archive", help="Archive a plant")
    p_pl_archive.add_argument("plantId", help="Plant ID")
    p_pl_archive.add_argument("--reason", help="Archive reason")
    p_pl_move = plants_sub.add_parser("move", help="Move a plant to a new location")
    p_pl_move.add_argument("plantId", help="Plant ID")
    p_pl_move.add_argument("--location", required=True, help="New location ID")
    p_pl_move.add_argument("--sublocation", help="New microzone ID")
    p_plants.set_defaults(func=cmd_plants)

    # locations
    p_locs = sub.add_parser("locations", help="Location operations")
    locs_sub = p_locs.add_subparsers(dest="subcmd")
    p_loc_list = locs_sub.add_parser("list", help="List locations")
    p_loc_get = locs_sub.add_parser("get", help="Get location details")
    p_loc_get.add_argument("locationId", help="Location ID")
    p_loc_add = locs_sub.add_parser("add", help="Add a location")
    p_loc_add.add_argument("--id", required=True, help="Location ID")
    p_loc_add.add_argument("--name", required=True, help="Display name")
    p_loc_add.add_argument("--type", required=True, choices=["balcony", "room", "other"])
    p_loc_add.add_argument("--indoor-outdoor", choices=["indoor", "outdoor"], default="indoor")
    p_loc_add.add_argument("--exposure", help="Exposure direction")
    p_loc_add.add_argument("--notes", help="Notes")
    p_loc_update = locs_sub.add_parser("update", help="Update location fields")
    p_loc_update.add_argument("locationId", help="Location ID")
    p_loc_update.add_argument("--data", required=True, help="JSON object with fields to update")
    p_locs.set_defaults(func=cmd_locations)

    # microzones
    p_mz = sub.add_parser("microzones", help="Microzone operations")
    mz_sub = p_mz.add_subparsers(dest="subcmd")
    p_mz_list = mz_sub.add_parser("list", help="List microzones")
    p_mz_list.add_argument("--location", help="Filter by locationId")
    p_mz_add = mz_sub.add_parser("add", help="Add a microzone")
    p_mz_add.add_argument("--id", required=True, help="Microzone ID")
    p_mz_add.add_argument("--location", required=True, help="Location ID")
    p_mz_add.add_argument("--name", required=True, help="Display name")
    p_mz_add.add_argument("--data", help="JSON object with additional fields")
    p_mz_update = mz_sub.add_parser("update", help="Update microzone fields")
    p_mz_update.add_argument("microzoneId", help="Microzone ID")
    p_mz_update.add_argument("--data", required=True, help="JSON object with fields to update")
    p_mz.set_defaults(func=cmd_microzones)

    # irrigation
    p_irr = sub.add_parser("irrigation", help="Irrigation system operations")
    irr_sub = p_irr.add_subparsers(dest="subcmd")
    irr_sub.add_parser("list", help="List irrigation systems")
    p_irr_get = irr_sub.add_parser("get", help="Get irrigation system details")
    p_irr_get.add_argument("systemId", help="Irrigation system ID")
    p_irr_update = irr_sub.add_parser("update", help="Update irrigation system")
    p_irr_update.add_argument("systemId", help="Irrigation system ID")
    p_irr_update.add_argument("--data", required=True, help="JSON object with fields to update")
    p_irr.set_defaults(func=cmd_irrigation)

    # profiles
    p_prof = sub.add_parser("profiles", help="Profile operations")
    prof_sub = p_prof.add_subparsers(dest="subcmd")
    p_prof_list = prof_sub.add_parser("list", help="List profiles")
    p_prof_list.add_argument("type", choices=["watering", "fertilization", "repotting", "pest", "maintenance", "healthcheck"])
    p_prof_list.add_argument("--plant", help="Filter by plant ID")
    p_prof_get = prof_sub.add_parser("get", help="Get profile")
    p_prof_get.add_argument("type", choices=["watering", "fertilization", "repotting", "pest", "maintenance", "healthcheck"])
    p_prof_get.add_argument("plantId", help="Plant ID")
    p_prof_set = prof_sub.add_parser("set", help="Set profile data")
    p_prof_set.add_argument("type", choices=["watering", "fertilization", "repotting", "pest", "maintenance", "healthcheck"])
    p_prof_set.add_argument("plantId", help="Plant ID")
    p_prof_set.add_argument("--data", required=True, help="JSON profile data")
    p_prof_remove = prof_sub.add_parser("remove", help="Remove a profile")
    p_prof_remove.add_argument("type", choices=["watering", "fertilization", "repotting", "pest", "maintenance", "healthcheck"])
    p_prof_remove.add_argument("plantId", help="Plant ID")
    p_prof.set_defaults(func=cmd_profiles)

    # events
    p_evt = sub.add_parser("events", help="Event operations")
    evt_sub = p_evt.add_subparsers(dest="subcmd")
    p_evt_log = evt_sub.add_parser("log", help="Log a new event")
    p_evt_log.add_argument("--type", required=True, help="Event type")
    p_evt_log.add_argument("--plant", help="Plant ID (single plant)")
    p_evt_log.add_argument("--plants", help="Comma-separated plant IDs")
    p_evt_log.add_argument("--location", help="Location ID")
    p_evt_log.add_argument("--scope", help="Scope description")
    p_evt_log.add_argument("--details", help="JSON details object")
    _add_effective_time_arguments(p_evt_log)
    p_evt_list = evt_sub.add_parser("list", help="List events")
    p_evt_list.add_argument("--plant", help="Filter by plant ID")
    p_evt_list.add_argument("--type", help="Filter by event type")
    p_evt_list.add_argument("--since", help="Filter events since date (YYYY-MM-DD)")
    p_evt_list.add_argument("--limit", type=int, default=20, help="Max events to return")
    p_evt_last = evt_sub.add_parser("last", help="Get last event for a plant")
    p_evt_last.add_argument("plantId", help="Plant ID")
    p_evt_last.add_argument("--type", help="Filter by event type")
    p_evt.set_defaults(func=cmd_events)

    # products
    p_prod = sub.add_parser("products", help="Product inventory operations")
    prod_sub = p_prod.add_subparsers(dest="subcmd")
    p_prod_list = prod_sub.add_parser("list", help="List products")
    p_prod_list.add_argument("--category", help="Filter by product category")
    p_prod_list.add_argument("--target-issue", help="Filter by target issue key")
    p_prod_get = prod_sub.add_parser("get", help="Get product details")
    p_prod_get.add_argument("productId", help="Product ID")
    p_prod_add = prod_sub.add_parser("add", help="Add a product")
    p_prod_add.add_argument("--display-name", required=True, help="Display name")
    p_prod_add.add_argument("--category", required=True, help="Product category")
    p_prod_add.add_argument("--description", required=True, help="Product description")
    p_prod_add.add_argument("--target-issues", help="Comma-separated issue keys")
    p_prod_add.add_argument("--photo-file", help="Source photo file to copy into media/products")
    p_prod_add.add_argument("--notes", help="Notes")
    p_prod_update = prod_sub.add_parser("update", help="Update product fields")
    p_prod_update.add_argument("productId", help="Product ID")
    p_prod_update.add_argument("--data", help="JSON object with fields to update")
    p_prod_update.add_argument("--display-name", help="Display name")
    p_prod_update.add_argument("--category", help="Product category")
    p_prod_update.add_argument("--description", help="Product description")
    p_prod_update.add_argument("--target-issues", help="Comma-separated issue keys")
    p_prod_update.add_argument("--photo-file", help="Replacement source photo file")
    p_prod_update.add_argument("--notes", help="Notes")
    p_prod_remove = prod_sub.add_parser("remove", help="Remove a product")
    p_prod_remove.add_argument("productId", help="Product ID")
    p_prod.set_defaults(func=cmd_products)

    # reminders
    p_rem = sub.add_parser("reminders", help="Reminder operations")
    rem_sub = p_rem.add_subparsers(dest="subcmd")
    p_rem_list = rem_sub.add_parser("list", help="List reminders")
    p_rem_list.add_argument("--status", help="Filter by status")
    p_rem_get = rem_sub.add_parser("get", help="Get reminder details")
    p_rem_get.add_argument("taskId", help="Task ID")
    p_rem_confirm = rem_sub.add_parser("confirm", help="Confirm a reminder task")
    p_rem_confirm.add_argument("taskId", help="Task ID")
    p_rem_confirm.add_argument("--details", help="Confirmation details")
    _add_effective_time_arguments(p_rem_confirm)
    p_rem_cancel = rem_sub.add_parser("cancel", help="Cancel a reminder task")
    p_rem_cancel.add_argument("taskId", help="Task ID")
    p_rem_cancel.add_argument("--reason", help="Cancellation reason")
    rem_sub.add_parser("reset", help="Clean up expired/stale tasks")
    rem_sub.add_parser("repair", help="Normalize and repair reminder state")
    p_rem.set_defaults(func=cmd_reminders)

    # eval
    p_eval = sub.add_parser("eval", help="Run care evaluation")
    eval_sub = p_eval.add_subparsers(dest="subcmd")
    p_eval_run = eval_sub.add_parser("run", help="Run full evaluation")
    p_eval_run.add_argument("--weather", help="JSON weather context")
    p_eval_run.add_argument("--dry-run", action="store_true", help="Don't update state")
    p_eval_status = eval_sub.add_parser("status", help="Quick status of what's due")
    eval_sub.add_parser("render", help="Render reminder text from eval JSON on stdin")
    p_eval.set_defaults(func=cmd_eval)

    # lookup
    p_look = sub.add_parser("lookup", help="External API plant lookups")
    look_sub = p_look.add_subparsers(dest="subcmd")
    p_look_search = look_sub.add_parser("search", help="Search for a plant species")
    p_look_search.add_argument("query", help="Plant name to search for")
    p_look_species = look_sub.add_parser("species", help="Get species details")
    p_look_species.add_argument("name", help="Scientific or common name")
    p_look_care = look_sub.add_parser("care", help="Get care recommendations")
    p_look_care.add_argument("name", help="Species or common name")
    p_look.set_defaults(func=cmd_lookup)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except EnvironmentError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Validation error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
