import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))
SPEC = importlib.util.spec_from_file_location(
    "loremaster_config_test_app", LOREMASTER_DIR / "loremaster.py")
LOREMASTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LOREMASTER
SPEC.loader.exec_module(LOREMASTER)


class ConfigRecoveryTests(unittest.TestCase):
    def load_payload(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loremaster_config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            original = LOREMASTER.CONFIG_PATH
            LOREMASTER.CONFIG_PATH = path
            try:
                return LOREMASTER.load_config()
            finally:
                LOREMASTER.CONFIG_PATH = original

    def test_valid_non_object_json_falls_back_to_defaults(self):
        for payload in (None, [], "unexpected", 42):
            with self.subTest(payload=payload):
                config = self.load_payload(payload)
                self.assertEqual(config["wiki_hotkey"], "Ctrl+Shift+E")
                self.assertEqual(config["opacity"], 1.0)
                self.assertFalse(config["summary_collapsed"])
                self.assertEqual(config["ui_theme"], "vellum")
                self.assertFalse(config["split_charmed_pet_dps"])
                self.assertFalse(config["sky_intel_enabled"])

    def test_legacy_visual_and_hotkey_defaults_migrate(self):
        config = self.load_payload({"opacity": 0.94, "wiki_hotkey": "Alt+E"})
        self.assertEqual(config["opacity"], 1.0)
        self.assertEqual(config["wiki_hotkey"], "Ctrl+Shift+E")
        self.assertEqual(config["ui_rendering_version"], 3)
        self.assertEqual(config["panel_size"], list(LOREMASTER.FULL_DEFAULT_SIZE))
        self.assertTrue(config["mez_timers_enabled"])
        self.assertFalse(config["mez_timer_sound"])
        self.assertEqual(config["mez_warning_seconds"], 10)
        self.assertTrue(config["lull_timers_enabled"])
        self.assertFalse(config["lull_timer_sound"])
        self.assertEqual(config["lull_warning_seconds"], 12)
        self.assertEqual(config["mini_alert_anchor"], "auto")
        self.assertEqual(config["starred_cards"], ["combat"])
        self.assertEqual(config["mini_stat_index"], 0)

    def test_rune_seed_migration_preserves_a_custom_panel_size(self):
        config = self.load_payload({
            "ui_rendering_version": 2,
            "panel_size": [612, 744],
        })
        self.assertEqual(config["ui_rendering_version"], 3)
        self.assertEqual(config["panel_size"], [612, 744])

    def test_explicit_custom_hotkey_and_opacity_are_preserved(self):
        config = self.load_payload({
            "opacity": 0.90,
            "wiki_hotkey": "Alt+E",
            "wiki_hotkey_customized": True,
        })
        self.assertEqual(config["opacity"], 0.90)
        self.assertEqual(config["wiki_hotkey"], "Alt+E")

    def test_explicit_collapsed_summary_choice_is_preserved(self):
        config = self.load_payload({"summary_collapsed": True})
        self.assertTrue(config["summary_collapsed"])

    def test_retired_compare_preferences_are_removed(self):
        config = self.load_payload({
            "compare_enabled": True,
            "compare_hotkey": "Ctrl+Shift+C",
            "compare_hotkey_customized": True,
            "compare_position": [10, 20],
        })
        for key in ("compare_enabled", "compare_hotkey",
                    "compare_hotkey_customized", "compare_position"):
            self.assertNotIn(key, config)

    def test_theme_and_sky_payload_are_sanitized(self):
        config = self.load_payload({
            "ui_theme": "GLASS",
            "sky_owned_items": "not-a-list",
            "sky_target_reward": ["too", "short"],
        })
        self.assertEqual(config["ui_theme"], "glass")
        self.assertEqual(config["sky_owned_items"], [])
        self.assertEqual(config["sky_target_reward"], [])

    def test_glass_palette_is_distinct_but_keeps_semantic_combat_colors(self):
        vellum = LOREMASTER.theme_palette("vellum")
        glass = LOREMASTER.theme_palette("glass")
        self.assertNotEqual(vellum["bg"], glass["bg"])
        self.assertEqual(glass["hp"], "#f25567")
        self.assertEqual(glass["mana"], "#5c8fff")

if __name__ == "__main__":
    unittest.main()
