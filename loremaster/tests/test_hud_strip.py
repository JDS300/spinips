"""Tests for the compact in-game HUD strip and its potential-mote tracker."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))
SPEC = importlib.util.spec_from_file_location(
    "loremaster_hud_test_app", LOREMASTER_DIR / "loremaster.py")
LOREMASTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LOREMASTER
SPEC.loader.exec_module(LOREMASTER)


class MoteTrackerTests(unittest.TestCase):
    def test_every_in_game_tier_name_buckets_in_tier_order(self):
        # The client names these items in the plural, but a loot line reads
        # "You have looted a <name>", so both spellings reach the ledger.
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "Motes of Infinitesimal Potential": 27,
                "Motes of Minor Potential": 32,
                "Motes of Lesser Potential": 3,
                "Motes of Potential": 2,
                "Motes of Major Potential": 1,
            }),
            [27, 32, 3, 2, 1],
        )
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "Mote of Infinitesimal Potential": 1,
                "Mote of Minor Potential": 1,
                "Mote of Lesser Potential": 1,
                "Mote of Potential": 1,
                "Mote of Major Potential": 1,
            }),
            [1, 1, 1, 1, 1],
        )

    def test_casing_and_spacing_do_not_split_a_tier(self):
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "motes of MINOR potential": 2,
                "  Mote  of  Minor  Potential  ": 3,
            }),
            [0, 5, 0, 0, 0],
        )

    def test_unrelated_and_near_miss_loot_is_never_counted(self):
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "Froglok Fine Mesh": 9,
                "Mote of Potential Greatness": 9,
                "Shard of Minor Potential": 9,
                "Motes of Major Potentials": 9,
                "Mote of Supreme Potential": 9,
            }),
            [0, 0, 0, 0, 0],
        )

    def test_malformed_ledger_entries_cannot_crash_the_strip(self):
        for loot in (None, [], "loot", 7):
            with self.subTest(loot=loot):
                self.assertEqual(
                    LOREMASTER.mote_tier_counts(loot), [0, 0, 0, 0, 0])
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "Mote of Minor Potential": None,
                "Mote of Major Potential": "many",
                "Mote of Lesser Potential": -4,
                "Mote of Potential": 3,
            }),
            [0, 0, 0, 3, 0],
        )

    def test_readout_is_slim_and_keeps_tier_one_on_the_left(self):
        self.assertEqual(
            LOREMASTER.fmt_mote_tiers([27, 32, 3, 2, 1]), "27/32/3/2/1")
        self.assertEqual(LOREMASTER.fmt_mote_tiers([0] * 5), "0/0/0/0/0")

    def test_tracker_is_a_first_class_card_with_a_strip_label(self):
        self.assertEqual(LOREMASTER.MINI_CARD_LABELS["motes"], "MOTES")
        self.assertEqual(len(LOREMASTER.MOTE_TIER_LABELS), 5)
        self.assertEqual(len(LOREMASTER.MOTE_GRADES), 5)


class StripGeometryTests(unittest.TestCase):
    def test_strip_can_shrink_below_its_starting_width(self):
        # The strip fits itself to its content; without a floor under the base
        # width it could only ever grow, which is what left dead space between
        # the last stat cell and the right-hand tools.
        self.assertLess(LOREMASTER.MINI_MIN_WIDTH, LOREMASTER.MINI_BASE_WIDTH)
        self.assertGreater(LOREMASTER.MINI_MIN_WIDTH, 0)

    def test_strip_seats_the_four_ledger_staples_plus_the_tracker(self):
        self.assertEqual(LOREMASTER.MINI_MAX_CELLS, 5)

    def test_settings_is_not_rebuilt_onto_the_glance_strip(self):
        source = (LOREMASTER_DIR / "loremaster.py").read_text(encoding="utf-8")
        self.assertNotIn("mini_settings", source)
        # It has to remain one click away on the DETAILS footer.
        self.assertIn('widgets["settings"] = tk.Label', source)


class StarredCardMigrationTests(unittest.TestCase):
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

    def test_existing_config_gains_the_tracker_once(self):
        config = self.load_payload(
            {"starred_cards": ["combat", "kills", "money", "progress"]})
        self.assertEqual(
            config["starred_cards"],
            ["combat", "kills", "money", "progress", "motes"])
        self.assertEqual(config["hud_cards_version"], 1)

    def test_a_deliberate_removal_is_not_undone_on_the_next_launch(self):
        config = self.load_payload({
            "starred_cards": ["combat", "kills"],
            "hud_cards_version": 1,
        })
        self.assertEqual(config["starred_cards"], ["combat", "kills"])

    def test_default_strip_ships_the_tracker_and_fits_the_cell_budget(self):
        config = self.load_payload({})
        self.assertIn("motes", config["starred_cards"])
        self.assertLessEqual(
            len(config["starred_cards"]), LOREMASTER.MINI_MAX_CELLS)

    def test_malformed_starred_cards_do_not_break_the_migration(self):
        config = self.load_payload({"starred_cards": "combat"})
        self.assertEqual(config["hud_cards_version"], 1)
        self.assertEqual(config["starred_cards"], "combat")


if __name__ == "__main__":
    unittest.main()
