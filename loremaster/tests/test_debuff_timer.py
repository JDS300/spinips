import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from debuff_timer import (  # noqa: E402
    DEBUFF_LANDING_COMPATIBILITY,
    DEBUFF_SPELLS,
    DebuffTracker,
    duration_ticks,
    format_debuff_remaining,
    resolve_debuff_spell,
)

BASE = datetime(2026, 8, 6, 12, 0, 0)
REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures" / "debuff_spell_reference.json").read_text())


def at(seconds):
    return BASE + timedelta(seconds=seconds)


def only_group(snapshot, target):
    matches = [g for g in snapshot.groups if g.target == target]
    assert len(matches) == 1, f"expected one group for {target!r}, got {matches}"
    return matches[0]


def only_row(snapshot, target):
    group = only_group(snapshot, target)
    assert len(group.rows) == 1, f"expected one row for {target!r}, got {group.rows}"
    return group.rows[0]


class DebuffCatalogTests(unittest.TestCase):
    def test_every_spell_reproduces_its_published_endpoints(self):
        """The scraped Allakhazam endpoints are the contract for the formulas."""
        checked = 0
        for spell in DEBUFF_SPELLS:
            for level, expected in spell.published_endpoints:
                self.assertEqual(
                    duration_ticks(spell, level), expected,
                    f"{spell.name} @L{level} expected {expected} ticks")
                checked += 1
        self.assertGreater(checked, 40)

    def test_table_matches_the_committed_reference_scrape(self):
        self.assertEqual({s.name for s in DEBUFF_SPELLS}, set(REFERENCE))
        for spell in DEBUFF_SPELLS:
            reference = REFERENCE[spell.name]
            self.assertEqual(spell.kind, reference["kind"], spell.name)
            self.assertEqual(spell.duration_cap_ticks, reference["cap_ticks"],
                             spell.name)

    def test_coverage_spans_the_three_families(self):
        kinds = {}
        for spell in DEBUFF_SPELLS:
            kinds[spell.kind] = kinds.get(spell.kind, 0) + 1
        self.assertGreaterEqual(kinds["slow"], 13)
        self.assertGreaterEqual(kinds["resist"], 16)
        self.assertGreaterEqual(kinds["dot"], 48)

    def test_fixed_duration_spells_ignore_caster_level(self):
        sicken = resolve_debuff_spell("Sicken").spell
        self.assertEqual(duration_ticks(sicken, 10), 14)
        self.assertEqual(duration_ticks(sicken, 60), 14)

    def test_slow_and_resist_use_only_known_formulas(self):
        """A typo in the table would surface as an unrecognised formula."""
        for kind, allowed in (
                ("slow", {"level_half_roundup", "level"}),
                ("resist", {"level_x2_plus10", "level_x3_plus10", "level", None})):
            found = {s.duration_formula for s in DEBUFF_SPELLS if s.kind == kind}
            self.assertTrue(found <= allowed, f"{kind}: unexpected {found - allowed}")

    def test_every_formula_named_in_the_table_exists(self):
        from debuff_timer import DURATION_FORMULAS
        for spell in DEBUFF_SPELLS:
            if spell.duration_formula is not None:
                self.assertIn(spell.duration_formula, DURATION_FORMULAS, spell.name)

    def test_cap_applies_before_rank_scaling(self):
        tagars = resolve_debuff_spell("Tagar's Insects").spell
        self.assertEqual(duration_ticks(tagars, 70), 35)
        self.assertEqual(duration_ticks(tagars, 70, rank=10), 70)

    def test_rank_suffix_is_read_from_the_spell_name(self):
        self.assertEqual(resolve_debuff_spell("Tagar's Insects Rk. II").rank, 2)
        self.assertEqual(resolve_debuff_spell("Tagar's Insects").rank, 0)

    def test_name_lookup_tolerates_case_and_apostrophes(self):
        for written in ("tagars insects", "TAGAR'S INSECTS", "Tagar’s Insects"):
            self.assertIsNotNone(resolve_debuff_spell(written), written)

    def test_unrelated_spells_do_not_resolve(self):
        self.assertIsNone(resolve_debuff_spell("Mesmerize"))
        self.assertIsNone(resolve_debuff_spell("Complete Heal"))
        self.assertIsNone(resolve_debuff_spell(None))

    def test_dots_are_exact_and_the_rest_are_conservative(self):
        self.assertEqual(resolve_debuff_spell("Sicken").duration_confidence, "exact")
        self.assertEqual(
            resolve_debuff_spell("Togor's Insects").duration_confidence,
            "conservative")
        self.assertEqual(resolve_debuff_spell("Malaise").duration_confidence,
                         "conservative")

    def test_the_shared_yawns_family_holds_the_whole_insect_line(self):
        """Six slows print the same line; correlation is what tells them apart."""
        self.assertEqual(DEBUFF_LANDING_COMPATIBILITY["yawns"], frozenset({
            "Drowsy", "Walking Sleep", "Tagar's Insects", "Togor's Insects",
            "Tigir's Insects", "Turgur's Insects"}))

    def test_a_shared_family_spans_meaningfully_different_durations(self):
        """If they all lasted the same, correlating to the cast would be moot."""
        ticks = {resolve_debuff_spell(name, 60).duration_ticks
                 for name in DEBUFF_LANDING_COMPATIBILITY["yawns"]}
        self.assertGreater(max(ticks) - min(ticks), 20)

    def test_the_level_60_tier_is_present(self):
        """The spells a level 60 character actually casts, which 0.5.0 missed."""
        for name, kind in (("Tashanian", "resist"), ("Forlorn Deeds", "slow"),
                           ("Torment of Argli", "dot"), ("Asphyxiate", "dot"),
                           ("Turgur's Insects", "slow"), ("Malo", "resist")):
            resolved = resolve_debuff_spell(name)
            self.assertIsNotNone(resolved, name)
            self.assertEqual(resolved.kind, kind, name)

    def test_no_beneficial_or_self_only_spell_is_tracked(self):
        """Torpor and the Lich line drain the caster, not the mob."""
        for name in ("Torpor", "Arch Lich", "Demi Lich",
                     "Ancient Master of Death"):
            self.assertIsNone(resolve_debuff_spell(name), name)

    def test_every_landing_family_is_reachable_from_the_table(self):
        declared = {s.landing_family for s in DEBUFF_SPELLS if s.landing_family}
        self.assertEqual(declared, set(DEBUFF_LANDING_COMPATIBILITY))

    def test_remaining_is_formatted_for_the_deck(self):
        self.assertEqual(format_debuff_remaining(150), "2:30")
        self.assertEqual(format_debuff_remaining(9), "9s")
        self.assertEqual(format_debuff_remaining(-3), "0s")


class DebuffTrackerTests(unittest.TestCase):
    def tracker(self, level=50):
        tracker = DebuffTracker()
        tracker.set_caster_level(level)
        return tracker

    def test_cast_alone_never_starts_a_timer(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        self.assertEqual(tracker.snapshot(at(1)).groups, ())

    def test_slow_landing_correlates_to_the_pending_cast(self):
        """Four slows share 'yawns'; the pending cast picks the duration."""
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(2.5))
        row = only_row(tracker.snapshot(at(2.5)), "an ice giant")
        self.assertEqual(row.spell, "Togor's Insects")
        self.assertEqual(row.remaining_seconds, 150.0)   # L50 -> 25 ticks

    def test_the_same_family_resolves_a_different_spell_to_its_own_duration(self):
        tracker = self.tracker()
        tracker.begin_cast("Drowsy", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(2))
        self.assertEqual(only_row(tracker.snapshot(at(2)), "an ice giant").spell,
                         "Drowsy")

    def test_landing_without_a_local_cast_is_ignored(self):
        """Another shaman's slow prints exactly the same line."""
        tracker = self.tracker()
        tracker.observe_landing("an ice giant", "yawns", at(1))
        self.assertEqual(tracker.snapshot(at(1)).groups, ())

    def test_a_nearby_cast_does_not_arm_the_tracker(self):
        tracker = self.tracker()
        tracker.observe_nearby_cast("Togor's Insects", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(2.5))
        self.assertEqual(tracker.snapshot(at(2.5)).groups, ())

    def test_a_stale_cast_cannot_claim_a_much_later_landing(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(600))
        self.assertEqual(tracker.snapshot(at(600)).groups, ())

    def test_resist_cancels_the_pending_cast(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_resist("Togor's Insects", at(2))
        tracker.observe_landing("an ice giant", "yawns", at(2.5))
        self.assertEqual(tracker.snapshot(at(2.5)).groups, ())

    def test_dot_starts_from_the_cast_and_attributes_from_the_tick(self):
        tracker = self.tracker()
        tracker.begin_cast("Envenomed Bolt", at(0))
        tracker.observe_dot_tick("an ice giant", "Envenomed Bolt", at(6))
        row = only_row(tracker.snapshot(at(6)), "an ice giant")
        self.assertEqual(row.spell, "Envenomed Bolt")
        self.assertEqual(row.kind, "dot")
        # 6 fixed ticks == 36s, counted from the cast rather than the tick.
        self.assertEqual(row.remaining_seconds, 30.0)

    def test_a_dot_ticking_mid_fight_is_still_tracked(self):
        """Loremaster may start reading the log after the DoT landed."""
        tracker = self.tracker()
        tracker.observe_dot_tick("an ice giant", "Envenomed Bolt", at(0))
        self.assertEqual(only_row(tracker.snapshot(at(0)), "an ice giant").spell,
                         "Envenomed Bolt")

    def test_a_dot_outlives_its_estimate_while_ticks_continue(self):
        """A focus item extends duration; the heartbeat is ground truth."""
        tracker = self.tracker()
        tracker.begin_cast("Envenomed Bolt", at(0))          # 6 ticks == 36s
        tracker.observe_dot_tick("an ice giant", "Envenomed Bolt", at(6))
        tracker.observe_dot_tick("an ice giant", "Envenomed Bolt", at(42))
        self.assertTrue(tracker.snapshot(at(43)).groups,
                        "a still-ticking DoT must not be dropped")

    def test_a_dot_that_stops_ticking_is_dropped(self):
        tracker = self.tracker()
        tracker.begin_cast("Envenomed Bolt", at(0))
        tracker.observe_dot_tick("an ice giant", "Envenomed Bolt", at(6))
        self.assertEqual(tracker.snapshot(at(200)).groups, ())

    def test_a_slow_lingers_briefly_past_its_estimate_then_goes(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(0))
        self.assertTrue(tracker.snapshot(at(153)).groups, "grace window")
        self.assertEqual(tracker.snapshot(at(200)).groups, ())

    def test_fade_clears_the_row(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(2))
        tracker.observe_fade("an ice giant", "Togor's Insects", at(30))
        self.assertEqual(tracker.snapshot(at(31)).groups, ())

    def test_kill_clears_every_row_on_that_target_only(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(2))
        tracker.begin_cast("Malaise", at(3))
        tracker.observe_landing("an ice giant", "malaise", at(5))
        tracker.begin_cast("Drowsy", at(6))
        tracker.observe_landing("a froglok tad", "yawns", at(7))
        self.assertEqual(len(only_group(tracker.snapshot(at(7)), "an ice giant").rows), 2)
        tracker.observe_kill("an ice giant", at(8))
        snapshot = tracker.snapshot(at(8))
        self.assertEqual([g.target for g in snapshot.groups], ["a froglok tad"])

    def test_a_kill_clears_the_row_despite_sentence_case(self):
        """EQ capitalises the first word of a line.

        The landing reads "An abhorrent yawns." and the kill reads "You have
        slain an abhorrent!", so the same mob arrives spelled two ways.
        """
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("An abhorrent", "yawns", at(1))
        tracker.observe_kill("an abhorrent", at(5))
        self.assertEqual(tracker.snapshot(at(6)).groups, ())

    def test_a_fade_clears_the_row_despite_sentence_case(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("An abhorrent", "yawns", at(1))
        tracker.observe_fade("an abhorrent", "Togor's Insects", at(5))
        self.assertEqual(tracker.snapshot(at(6)).groups, ())

    def test_a_dot_tick_refreshes_the_row_despite_sentence_case(self):
        tracker = self.tracker()
        tracker.begin_cast("Envenomed Bolt", at(0))
        tracker.observe_dot_tick("An abhorrent", "Envenomed Bolt", at(6))
        tracker.observe_dot_tick("an abhorrent", "Envenomed Bolt", at(12))
        group = only_group(tracker.snapshot(at(12)), "An abhorrent")
        self.assertEqual(len(group.rows), 1, "must not split into two mobs")

    def test_the_row_keeps_the_name_as_first_seen(self):
        """Keying is case-insensitive; the deck still shows readable text."""
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("An abhorrent", "yawns", at(1))
        self.assertEqual(tracker.snapshot(at(1)).groups[0].target, "An abhorrent")

    def test_recast_on_the_same_target_resets_the_timer(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(2))
        first = only_row(tracker.snapshot(at(2)), "an ice giant").expires_at
        tracker.begin_cast("Togor's Insects", at(60))
        tracker.observe_landing("an ice giant", "yawns", at(62))
        second = only_row(tracker.snapshot(at(62)), "an ice giant").expires_at
        self.assertGreater(second, first)

    def test_two_debuffs_on_one_mob_share_a_group(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(1))
        tracker.begin_cast("Tashani", at(2))
        tracker.observe_landing("an ice giant", "tashan", at(3))
        group = only_group(tracker.snapshot(at(3)), "an ice giant")
        self.assertEqual({row.spell for row in group.rows},
                         {"Togor's Insects", "Tashani"})

    def test_rows_within_a_group_are_sorted_by_remaining_time(self):
        tracker = self.tracker()
        tracker.begin_cast("Tashani", at(0))          # 110 ticks
        tracker.observe_landing("an ice giant", "tashan", at(1))
        tracker.begin_cast("Togor's Insects", at(2))  # 25 ticks
        tracker.observe_landing("an ice giant", "yawns", at(3))
        rows = only_group(tracker.snapshot(at(3)), "an ice giant").rows
        self.assertEqual([row.spell for row in rows],
                         ["Togor's Insects", "Tashani"])

    def test_the_mob_limit_reports_overflow(self):
        tracker = self.tracker()
        for index in range(9):
            tracker.begin_cast("Envenomed Bolt", at(index))
            tracker.observe_dot_tick(f"mob {index}", "Envenomed Bolt",
                                     at(index + 0.5))
        snapshot = tracker.snapshot(at(9), limit=6)
        self.assertEqual(len(snapshot.groups), 6)
        self.assertEqual(snapshot.overflow, 3)

    def test_kind_filter_hides_disabled_families(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(1))
        tracker.begin_cast("Envenomed Bolt", at(2))
        tracker.observe_dot_tick("an ice giant", "Envenomed Bolt", at(3))
        rows = only_group(tracker.snapshot(at(3), kinds=frozenset({"dot"})),
                          "an ice giant").rows
        self.assertEqual([row.spell for row in rows], ["Envenomed Bolt"])

    def test_group_urgency_reports_its_most_urgent_row(self):
        tracker = self.tracker()
        tracker.begin_cast("Tashani", at(0))
        tracker.observe_landing("an ice giant", "tashan", at(0))
        tracker.begin_cast("Togor's Insects", at(1))
        tracker.observe_landing("an ice giant", "yawns", at(1))
        group = only_group(tracker.snapshot(at(148)), "an ice giant")
        self.assertEqual(group.urgency, "critical")

    def test_clear_resets_everything(self):
        tracker = self.tracker()
        tracker.begin_cast("Togor's Insects", at(0))
        tracker.observe_landing("an ice giant", "yawns", at(1))
        self.assertEqual(tracker.clear(), 1)
        self.assertEqual(tracker.snapshot(at(2)).groups, ())

    def test_caster_level_changes_the_duration(self):
        low = self.tracker(level=27)
        low.begin_cast("Tagar's Insects", at(0))
        low.observe_landing("an ice giant", "yawns", at(0))
        high = self.tracker(level=70)
        high.begin_cast("Tagar's Insects", at(0))
        high.observe_landing("an ice giant", "yawns", at(0))
        self.assertEqual(only_row(low.snapshot(at(0)), "an ice giant").remaining_seconds,
                         14 * 6)
        self.assertEqual(only_row(high.snapshot(at(0)), "an ice giant").remaining_seconds,
                         35 * 6)


if __name__ == "__main__":
    unittest.main()
