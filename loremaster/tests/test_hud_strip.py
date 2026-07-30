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
    GRADES = ("Infinitesimal", "Minor", "Lesser", None, "Major", "Greater",
              "Superior", "Grand", "Ascendant", "Infinite")
    EXP = (1, 1, 2, 4, 5, 6, 7, 8, 9, 10)

    def name(self, grade, plural=False):
        stem = "Motes" if plural else "Mote"
        return f"{stem} of Potential" if grade is None else (
            f"{stem} of {grade} Potential")

    def test_all_ten_in_game_grades_bucket_in_tier_order(self):
        # The client names these items in the plural, but a loot line reads
        # "You have looted a <name>", so both spellings reach the ledger.
        for plural in (False, True):
            with self.subTest(plural=plural):
                loot = {self.name(g, plural): i + 1
                        for i, g in enumerate(self.GRADES)}
                self.assertEqual(
                    LOREMASTER.mote_tier_counts(loot), list(range(1, 11)))

    def test_infinite_and_infinitesimal_never_merge(self):
        # They share a prefix, so a prefix match would silently fold the rarest
        # grade into the most common one.
        self.assertEqual(
            LOREMASTER.mote_tier_counts(
                {"Mote of Infinitesimal Potential": 4})[0], 4)
        self.assertEqual(
            LOREMASTER.mote_tier_counts(
                {"Mote of Infinite Potential": 4})[9], 4)

    def test_exp_total_uses_each_grade_own_value(self):
        self.assertEqual(LOREMASTER.MOTE_TIER_EXP, self.EXP)
        self.assertEqual(LOREMASTER.mote_exp_total([1] * 10), sum(self.EXP))
        self.assertEqual(LOREMASTER.mote_exp_total([0] * 10), 0)
        self.assertEqual(LOREMASTER.mote_exp_total([2] + [0] * 9), 2)
        self.assertEqual(LOREMASTER.mote_exp_total([0] * 9 + [3]), 30)

    def test_casing_and_spacing_do_not_split_a_tier(self):
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "motes of MINOR potential": 2,
                "  Mote  of  Minor  Potential  ": 3,
            }),
            [0, 5] + [0] * 8,
        )

    def test_unrelated_and_near_miss_loot_is_never_counted(self):
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "Froglok Fine Mesh": 9,
                "Mote of Potential Greatness": 9,
                "Shard of Minor Potential": 9,
                "Motes of Major Potentials": 9,
                "Mote of Supreme Potential": 9,
                "Mote of Infinites Potential": 9,
            }),
            [0] * 10,
        )

    def test_malformed_ledger_entries_cannot_crash_the_strip(self):
        for loot in (None, [], "loot", 7):
            with self.subTest(loot=loot):
                self.assertEqual(
                    LOREMASTER.mote_tier_counts(loot), [0] * 10)
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "Mote of Minor Potential": None,
                "Mote of Major Potential": "many",
                "Mote of Lesser Potential": -4,
                "Mote of Potential": 3,
            }),
            [0, 0, 0, 3] + [0] * 6,
        )

    def test_readout_stops_at_the_highest_grade_that_dropped(self):
        # Printing all ten grades would be a twenty-character cell; the cell
        # has to stay slim until a rare grade earns the space.
        self.assertEqual(
            LOREMASTER.fmt_mote_tiers([27, 32, 3, 2, 1] + [0] * 5),
            "27/32/3/2/1")
        self.assertEqual(LOREMASTER.fmt_mote_tiers([5] + [0] * 9), "5")
        self.assertEqual(
            LOREMASTER.fmt_mote_tiers([0] * 9 + [1]), "0/0/0/0/0/0/0/0/0/1")

    def test_readout_is_a_dash_when_nothing_has_dropped(self):
        for counts in ([0] * 10, [], None):
            with self.subTest(counts=counts):
                self.assertEqual(LOREMASTER.fmt_mote_tiers(counts), "\u2014")

    def test_tracker_is_a_first_class_card_with_a_strip_label(self):
        self.assertEqual(LOREMASTER.MINI_CARD_LABELS["motes"], "MOTES")
        self.assertEqual(len(LOREMASTER.MOTE_TIERS), 10)
        self.assertEqual(len(LOREMASTER.MOTE_TIER_LABELS), 10)
        self.assertEqual(len(LOREMASTER.MOTE_GRADES), 10)
        # Exactly one grade carries no grade word: the unqualified fourth.
        self.assertEqual(
            [i for i, g in enumerate(LOREMASTER.MOTE_GRADES) if not g], [3])


class StripGeometryTests(unittest.TestCase):
    def test_strip_can_shrink_below_its_starting_width(self):
        # The strip fits itself to its content; without a floor under the base
        # width it could only ever grow, which is what left dead space between
        # the last stat cell and the right-hand tools.
        self.assertLess(LOREMASTER.MINI_MIN_WIDTH, LOREMASTER.MINI_BASE_WIDTH)
        self.assertGreater(LOREMASTER.MINI_MIN_WIDTH, 0)

    def test_strip_seats_four_cells(self):
        self.assertEqual(LOREMASTER.MINI_MAX_CELLS, 4)

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

    def test_existing_config_gains_the_tracker_and_drops_progression(self):
        config = self.load_payload(
            {"starred_cards": ["combat", "kills", "money", "progress"]})
        self.assertEqual(
            config["starred_cards"], ["combat", "kills", "money", "motes"])
        self.assertEqual(config["hud_cards_version"], 2)

    def test_a_config_that_already_saw_v1_still_drops_progression(self):
        config = self.load_payload({
            "starred_cards": ["combat", "progress", "motes"],
            "hud_cards_version": 1,
        })
        self.assertEqual(config["starred_cards"], ["combat", "motes"])
        self.assertEqual(config["hud_cards_version"], 2)

    def test_a_deliberate_choice_is_not_undone_on_the_next_launch(self):
        config = self.load_payload({
            "starred_cards": ["combat", "kills", "progress"],
            "hud_cards_version": 2,
        })
        self.assertEqual(
            config["starred_cards"], ["combat", "kills", "progress"])

    def test_default_strip_ships_the_tracker_and_fits_the_cell_budget(self):
        config = self.load_payload({})
        self.assertIn("motes", config["starred_cards"])
        self.assertLessEqual(
            len(config["starred_cards"]), LOREMASTER.MINI_MAX_CELLS)

    def test_malformed_starred_cards_do_not_break_the_migration(self):
        config = self.load_payload({"starred_cards": "combat"})
        self.assertEqual(config["hud_cards_version"], 2)
        self.assertEqual(config["starred_cards"], "combat")


if __name__ == "__main__":
    unittest.main()
