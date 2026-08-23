"""End-to-end log grammar and model seams for debuff timer tracking."""

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))
SPEC = importlib.util.spec_from_file_location(
    "loremaster_debuff_integration_app", LOREMASTER_DIR / "loremaster.py")
LOREMASTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LOREMASTER
SPEC.loader.exec_module(LOREMASTER)

from debuff_timer import DebuffTracker  # noqa: E402

BASE = datetime(2026, 8, 6, 19, 0, 0)


def parsed(message, offset=0):
    stamp = (BASE + timedelta(seconds=offset)).strftime(LOREMASTER.TS_FORMAT)
    event = LOREMASTER.parse_line(f"[{stamp}] {message}")
    if event is None:
        raise AssertionError(f"line did not parse: {message}")
    return event


def at(seconds):
    return BASE + timedelta(seconds=seconds)


class DebuffLogGrammarTests(unittest.TestCase):
    def test_each_landing_family_has_its_own_kind(self):
        cases = {
            "an ice giant yawns.": ("debuff_landed_yawns", "an ice giant"),
            "a froglok tad slows down.": ("debuff_landed_slows_down",
                                          "a froglok tad"),
            "an ice giant feels lethargic.": ("debuff_landed_lethargic",
                                              "an ice giant"),
            "an ice giant glances nervously about.": ("debuff_landed_tashan",
                                                      "an ice giant"),
        }
        for message, (expected_kind, expected_target) in cases.items():
            _ts, kind, groups = parsed(message)
            self.assertEqual(kind, expected_kind, message)
            self.assertEqual(groups["target"], expected_target, message)

    def test_the_three_malaise_ranks_never_collide(self):
        """They differ only by an adverb, so anchoring is load-bearing."""
        cases = {
            "an ice giant looks somewhat uncomfortable.": "debuff_landed_malaise",
            "an ice giant looks uncomfortable.": "debuff_landed_malaisement",
            "an ice giant looks very uncomfortable.": "debuff_landed_malosi",
        }
        for message, expected in cases.items():
            matched = [kind for kind, pattern in LOREMASTER.PATTERNS
                       if pattern.match(message)]
            self.assertEqual(matched[:1], [expected], (message, matched))

    def test_landing_prose_never_reaches_dps_state(self):
        for kind in LOREMASTER.DEBUFF_LANDING_KINDS:
            self.assertIn(kind, LOREMASTER.CONTROL_ONLY_KINDS, kind)


class DebuffParserModelTests(unittest.TestCase):
    def setUp(self):
        self.stats = LOREMASTER.SessionStats("Spin")
        self.stats.level = 50
        self.mez = LOREMASTER.MezTracker()
        self.debuffs = DebuffTracker()
        self.debuffs.set_caster_level(50)

    def apply(self, message, offset=0):
        ts, kind, groups = parsed(message, offset)
        LOREMASTER.apply_log_models(
            self.stats, self.mez, ts, kind, groups,
            debuff_tracker=self.debuffs, caster_level=50)

    def only_row(self, offset, target):
        groups = [g for g in self.debuffs.snapshot(at(offset)).groups
                  if g.target == target]
        self.assertEqual(len(groups), 1, f"expected one group for {target!r}")
        self.assertEqual(len(groups[0].rows), 1, "expected one row")
        return groups[0].rows[0]

    def test_slow_lands_from_real_log_prose(self):
        self.apply("You begin casting Togor's Insects.", 0)
        self.apply("an ice giant yawns.", 2)
        row = self.only_row(2, "an ice giant")
        self.assertEqual(row.spell, "Togor's Insects")
        self.assertEqual(row.kind, "slow")
        self.assertEqual(row.duration_confidence, "conservative")

    def test_the_pending_cast_picks_the_duration_within_a_shared_family(self):
        self.apply("You begin casting Drowsy.", 0)
        self.apply("an ice giant yawns.", 2)
        self.assertEqual(self.only_row(2, "an ice giant").spell, "Drowsy")

    def test_another_players_slow_is_ignored(self):
        self.apply("Zarthok begins casting Togor's Insects.", 0)
        self.apply("an ice giant yawns.", 2)
        self.assertEqual(self.debuffs.snapshot(at(2)).groups, ())

    def test_dot_tick_drives_the_tracker(self):
        self.apply("You begin casting Envenomed Bolt.", 0)
        self.apply("an ice giant has taken 110 damage from your Envenomed Bolt.", 6)
        row = self.only_row(6, "an ice giant")
        self.assertEqual(row.spell, "Envenomed Bolt")
        self.assertEqual(row.kind, "dot")
        self.assertEqual(row.duration_confidence, "exact")

    def test_dot_damage_still_reaches_dps_state(self):
        """The tick is evidence for the timer without being stolen from DPS."""
        self.apply("You begin casting Envenomed Bolt.", 0)
        self.apply("an ice giant has taken 110 damage from your Envenomed Bolt.", 6)
        self.assertGreater(
            self.stats.damage_by_source["DoT: Envenomed Bolt"]["t"], 0)

    def test_another_players_dot_never_reaches_our_deck(self):
        """dot_third carries "by <caster>" and belongs to somebody else."""
        self.apply(
            "an ice giant has taken 110 damage from Envenomed Bolt by Zarthok.", 0)
        self.assertEqual(self.debuffs.snapshot(at(1)).groups, ())

    def test_our_own_dot_and_a_strangers_are_told_apart(self):
        self.apply("You begin casting Envenomed Bolt.", 0)
        self.apply("a froglok tad has taken 110 damage from your Envenomed Bolt.", 6)
        self.apply(
            "an ice giant has taken 110 damage from Envenomed Bolt by Zarthok.", 7)
        snapshot = self.debuffs.snapshot(at(8))
        self.assertEqual([group.target for group in snapshot.groups],
                         ["a froglok tad"])

    def test_resist_line_stops_the_timer_from_arming(self):
        self.apply("You begin casting Togor's Insects.", 0)
        self.apply("an ice giant resisted your Togor's Insects!", 2)
        self.apply("an ice giant yawns.", 3)
        self.assertEqual(self.debuffs.snapshot(at(3)).groups, ())

    def test_fade_line_clears_the_row(self):
        self.apply("You begin casting Togor's Insects.", 0)
        self.apply("an ice giant yawns.", 2)
        self.apply("Your Togor's Insects spell has worn off of an ice giant.", 40)
        self.assertEqual(self.debuffs.snapshot(at(41)).groups, ())

    def test_death_clears_every_row_on_that_mob(self):
        self.apply("You begin casting Togor's Insects.", 0)
        self.apply("an ice giant yawns.", 2)
        self.apply("You begin casting Tashani.", 3)
        self.apply("an ice giant glances nervously about.", 5)
        self.assertEqual(
            len(self.debuffs.snapshot(at(5)).groups[0].rows), 2)
        self.apply("You have slain an ice giant!", 10)
        self.assertEqual(self.debuffs.snapshot(at(10)).groups, ())

    def test_a_full_raid_shape_groups_by_mob(self):
        self.apply("You begin casting Togor's Insects.", 0)
        self.apply("an ice giant yawns.", 2)
        self.apply("You begin casting Tashani.", 3)
        self.apply("an ice giant glances nervously about.", 5)
        self.apply("You begin casting Envenomed Bolt.", 6)
        self.apply("a froglok tad has taken 110 damage from your Envenomed Bolt.", 12)
        snapshot = self.debuffs.snapshot(at(12))
        self.assertEqual(
            {group.target for group in snapshot.groups},
            {"an ice giant", "a froglok tad"})
        by_target = {group.target: group for group in snapshot.groups}
        self.assertEqual(len(by_target["an ice giant"].rows), 2)
        self.assertEqual(len(by_target["a froglok tad"].rows), 1)

    def test_level_up_line_updates_the_caster_level(self):
        tracker = DebuffTracker()
        ts, kind, groups = parsed("You have gained a level! Welcome to level 44!", 0)
        LOREMASTER.observe_debuff_log_event(tracker, ts, kind, groups)
        self.assertEqual(tracker.caster_level, 44)


if __name__ == "__main__":
    unittest.main()
