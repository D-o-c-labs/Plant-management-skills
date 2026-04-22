import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from test_support import plant_test_env

from plant_mgmt import render
from plant_mgmt_cli import build_parser, main


def _action(
    name,
    *,
    location_id="kitchen",
    location_name="Kitchen",
    suggested_action="water_if_dry",
    urgency="high",
    action_type="watering_check",
    sublocation_id=None,
    sublocation_name=None,
):
    return {
        "displayName": name,
        "plantId": f"plant_{name.lower()}",
        "locationId": location_id,
        "locationDisplayName": location_name,
        "subLocationId": sublocation_id,
        "subLocationDisplayName": sublocation_name,
        "suggestedAction": suggested_action,
        "urgency": urgency,
        "type": action_type,
    }


class RenderMessageTest(unittest.TestCase):
    def test_empty_actions_return_none(self):
        self.assertIsNone(render.render_message([]))

    def test_auto_irrigation_summary_renders_without_actions(self):
        message = render.render_message(
            [],
            locale="en",
            auto_irrigation={
                "emittedEvents": [
                    {"eventId": "evt_1", "systemId": "main", "effectiveDateLocal": "2026-04-22", "plantCount": 2}
                ],
                "backfilledDates": ["2026-04-22"],
                "skippedSystems": [],
            },
        )
        self.assertEqual(message, "💧 Auto-irrigation logged for 2 plants (1 dates backfilled).")

    def test_auto_irrigation_summary_is_prepended_to_actions(self):
        message = render.render_message(
            [_action("Basil")],
            locale="en",
            auto_irrigation={
                "emittedEvents": [
                    {"eventId": "evt_1", "systemId": "main", "effectiveDateLocal": "2026-04-22", "plantCount": 2}
                ],
                "backfilledDates": ["2026-04-22"],
                "skippedSystems": [],
            },
        )
        self.assertEqual(
            message,
            "💧 Auto-irrigation logged for 2 plants (1 dates backfilled).\n\n"
            "💧 Probable watering for Basil at Kitchen.",
        )

    def test_locale_normalization_falls_back_to_english(self):
        self.assertEqual(render.normalize_locale("it-IT"), "it")
        self.assertEqual(render.normalize_locale("fr-FR"), "en")
        self.assertEqual(
            render.render_message([_action("Basil")], locale="it-IT"),
            "💧 Probabile acqua per Basil a Kitchen.",
        )

    def test_single_group_single_plant_renders_sentence_in_english(self):
        message = render.render_message([_action("Basil")], locale="en")
        self.assertEqual(message, "💧 Probable watering for Basil at Kitchen.")

    def test_single_group_two_plants_renders_sentence_with_and(self):
        message = render.render_message([_action("Basil"), _action("Mint")], locale="en")
        self.assertEqual(message, "💧 Probable watering for Basil and Mint at Kitchen.")

    def test_single_group_three_plants_uses_block_format(self):
        message = render.render_message(
            [_action("Basil"), _action("Mint"), _action("Thyme")],
            locale="en",
        )
        self.assertEqual(
            message,
            "💧 Probable watering — Kitchen:\n"
            "  • Basil\n"
            "  • Mint\n"
            "  • Thyme",
        )

    def test_multiple_groups_use_block_format(self):
        message = render.render_message(
            [
                _action("Basil", location_id="balcony", location_name="Balcony", urgency="critical"),
                _action(
                    "Fern",
                    location_id="hall",
                    location_name="Hall",
                    suggested_action="inspect_plant_health",
                    urgency="medium",
                    action_type="healthcheck_check",
                ),
            ],
            locale="en",
        )
        self.assertEqual(
            message,
            "⚠️ Urgent: 💧 Probable watering — Balcony:\n"
            "  • Basil\n\n"
            "🔍 Health check — Hall:\n"
            "  • Fern",
        )

    def test_homogeneous_critical_group_uses_urgent_prefix_on_header(self):
        message = render.render_message(
            [
                _action("Basil", urgency="critical"),
                _action("Mint", urgency="critical"),
                _action("Thyme", urgency="critical"),
            ],
            locale="en",
        )
        self.assertEqual(
            message,
            "⚠️ Urgent: 💧 Probable watering — Kitchen:\n"
            "  • Basil\n"
            "  • Mint\n"
            "  • Thyme",
        )

    def test_mixed_urgency_group_uses_neutral_header_and_per_plant_tag(self):
        message = render.render_message(
            [
                _action("Basil", urgency="critical"),
                _action("Mint", urgency="medium"),
            ],
            locale="en",
        )
        self.assertEqual(
            message,
            "💧 Probable watering — Kitchen:\n"
            "  • Basil ⚠️ urgent\n"
            "  • Mint",
        )

    def test_mixed_urgency_forces_block_format_for_single_group(self):
        message = render.render_message(
            [
                _action("Basil", urgency="critical"),
                _action("Mint", urgency="high"),
            ],
            locale="en",
        )
        self.assertIn("— Kitchen:", message)
        self.assertIn("  • Basil ⚠️ urgent", message)

    def test_microzone_present_is_rendered_parenthetically(self):
        message = render.render_message(
            [_action("Basil", sublocation_id="window", sublocation_name="Near window")],
            locale="en",
        )
        self.assertEqual(message, "💧 Probable watering for Basil (Near window) at Kitchen.")

    def test_microzone_absent_is_omitted(self):
        message = render.render_message([_action("Basil")], locale="en")
        self.assertNotIn("(", message)

    def test_unknown_suggested_action_uses_humanized_fallback(self):
        message = render.render_message(
            [_action("Basil", suggested_action="mist_leaves", action_type="maintenance_check")],
            locale="en",
        )
        self.assertEqual(message, "Mist Leaves for Basil at Kitchen.")

    def test_missing_suggested_action_falls_back_to_type(self):
        action = _action("Fern", suggested_action=None, action_type="inspect_for_rot")
        message = render.render_message([action], locale="en")
        self.assertEqual(message, "Inspect For Rot for Fern at Kitchen.")

    def test_italian_locale_uses_localized_labels_and_template(self):
        message = render.render_message(
            [_action("Basilico", location_name="Cucina")],
            locale="it",
        )
        self.assertEqual(message, "💧 Probabile acqua per Basilico a Cucina.")


class RenderCliTest(unittest.TestCase):
    def test_eval_render_outputs_raw_text(self):
        with plant_test_env():
            parser = build_parser()
            args = parser.parse_args(["eval", "render"])
            stdin = io.StringIO(json.dumps({"actions": [_action("Basil")]}))
            stdout = io.StringIO()

            with patch("sys.stdin", stdin), redirect_stdout(stdout):
                args.func(args)

            self.assertEqual(stdout.getvalue(), "💧 Probable watering for Basil at Kitchen.\n")

    def test_eval_render_outputs_wrapped_json(self):
        with plant_test_env():
            parser = build_parser()
            args = parser.parse_args(["--json", "eval", "render"])
            stdin = io.StringIO(json.dumps({"actions": [_action("Basil")]}))
            stdout = io.StringIO()

            with patch("sys.stdin", stdin), redirect_stdout(stdout):
                args.func(args)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload, {"message": "💧 Probable watering for Basil at Kitchen."})

    def test_eval_render_passes_auto_irrigation_payload(self):
        with plant_test_env():
            parser = build_parser()
            args = parser.parse_args(["eval", "render"])
            stdin = io.StringIO(json.dumps({
                "actions": [],
                "autoIrrigation": {
                    "emittedEvents": [
                        {
                            "eventId": "evt_1",
                            "systemId": "main",
                            "effectiveDateLocal": "2026-04-22",
                            "plantCount": 3,
                        }
                    ],
                    "backfilledDates": ["2026-04-22"],
                    "skippedSystems": [],
                },
            }))
            stdout = io.StringIO()

            with patch("sys.stdin", stdin), redirect_stdout(stdout):
                args.func(args)

            self.assertEqual(stdout.getvalue(), "💧 Auto-irrigation logged for 3 plants (1 dates backfilled).\n")

    def test_eval_render_invalid_json_exits_with_stderr_message(self):
        with plant_test_env():
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch.object(sys, "argv", ["plant_mgmt", "eval", "render"]),
                patch("sys.stdin", io.StringIO("{not-json")),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit) as exc,
            ):
                main()

            self.assertEqual(exc.exception.code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("Validation error:", stderr.getvalue())
            self.assertIn("eval render expects JSON on stdin with an 'actions' array.", stderr.getvalue())

    def test_eval_render_missing_actions_key_exits_with_stderr_message(self):
        with plant_test_env():
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch.object(sys, "argv", ["plant_mgmt", "eval", "render"]),
                patch("sys.stdin", io.StringIO(json.dumps({"summary": {}}))),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit) as exc,
            ):
                main()

            self.assertEqual(exc.exception.code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("Validation error:", stderr.getvalue())
            self.assertIn("eval render expects JSON on stdin with an 'actions' array.", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
