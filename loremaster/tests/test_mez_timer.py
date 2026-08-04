import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from mez_timer import (  # noqa: E402
    MEZ_SPELLS,
    MezTracker,
    format_mez_remaining,
    mez_urgency,
    resolve_mez_spell,
    scaled_duration_ticks,
)


BASE = datetime(2026, 8, 3, 12, 0, 0)


class MezSpellCatalogTests(unittest.TestCase):
    def test_verified_spell_table(self):
        actual = {
            spell.name: (spell.base_ticks, spell.area) for spell in MEZ_SPELLS
        }
        self.assertEqual(actual, {
            "Mesmerize": (4, False),
            "Enthrall": (8, False),
            "Mesmerization": (4, True),
            "Entrancing Lights": (1, True),
            "Entrance": (12, False),
            "Dazzle": (16, False),
            "Fascination": (6, True),
            "Glamour of Kintaz": (9, False),
            "Rapture": (7, False),
            "Screaming Terror": (3, False),
            "Kelin's Lucid Lullaby": (3, False),
            "Crission's Pixie Strike": (3, False),
            "Sionachie's Dreams": (3, False),
        })

    def test_names_are_case_and_apostrophe_tolerant(self):
        cases = {
            "MESMERIZE": "Mesmerize",
            "glamour of kintaz": "Glamour of Kintaz",
            "kelins lucid lullaby": "Kelin's Lucid Lullaby",
            "Crission\u2019s Pixie Strike": "Crission's Pixie Strike",
            "Sionachies Dreams": "Sionachie's Dreams",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(resolve_mez_spell(raw).name, expected)
        # Glamour is a separate Shaman charisma buff, not a mez alias.
        self.assertIsNone(resolve_mez_spell("Glamour"))

    def test_roman_numeric_plus_and_labeled_rank_suffixes(self):
        cases = {
            "Enthrall II": 2,
            "Enthrall 2": 2,
            "Enthrall +2": 2,
            "Enthrall Rank II": 2,
            "Enthrall Rk. 2": 2,
            "Enthrall (II)": 2,
            "Enthrall (Rank II)": 2,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(resolve_mez_spell(raw).rank, expected)

    def test_duration_scaling_is_exact_whole_tick_half_up(self):
        self.assertEqual(scaled_duration_ticks(5, 1), 6)   # 5.5 -> 6
        self.assertEqual(scaled_duration_ticks(8, 2), 10)  # 9.6 -> 10
        self.assertEqual(
            resolve_mez_spell("Glamour of Kintaz +1").duration_seconds, 60)
        self.assertEqual(resolve_mez_spell("Enthrall II").duration_seconds, 60)
        self.assertEqual(resolve_mez_spell("Dazzle V").duration_seconds, 144)

    def test_ranked_cast_time_uses_the_non_nuke_track(self):
        self.assertEqual(resolve_mez_spell("Mesmerize").cast_seconds, 2.5)
        self.assertAlmostEqual(
            resolve_mez_spell("Mesmerization V").cast_seconds, 2.4)
        self.assertAlmostEqual(
            resolve_mez_spell("Entrancing Lights X").cast_seconds, 0.9)

    def test_actorless_landing_families_match_shared_log_prose(self):
        mesmerized = {
            resolve_mez_spell(name).spell.landing_family
            for name in ("Mesmerize", "Mesmerization", "Dazzle")
        }
        pixie = {
            resolve_mez_spell(name).spell.landing_family
            for name in ("Crission's Pixie Strike", "Sionachie's Dreams")
        }
        self.assertEqual(mesmerized, {"mesmerized"})
        self.assertEqual(pixie, {"pixie"})
        self.assertNotEqual(
            resolve_mez_spell("Enthrall").spell.landing_family,
            "mesmerized",
        )

    def test_unknown_or_malformed_names_do_not_resolve(self):
        self.assertIsNone(resolve_mez_spell("Root"))
        # Solon's Song is a charm song, not a mez; charm ownership has its own
        # tracker and must never produce a misleading mez countdown.
        self.assertIsNone(resolve_mez_spell("Solon's Song of the Sirens"))
        self.assertIsNone(resolve_mez_spell("Mesmerize IIII"))
        self.assertIsNone(resolve_mez_spell(None))


class MezCastCorrelationTests(unittest.TestCase):
    def test_timer_starts_on_confirmed_landing_not_cast_begin(self):
        tracker = MezTracker()
        pending = tracker.begin_cast("Mesmerize", BASE)
        self.assertEqual(pending.resolved.duration_seconds, 24)
        self.assertEqual(tracker.snapshot(BASE).active_count, 0)

        row = tracker.observe_landing("a gnoll", BASE + timedelta(seconds=2))
        self.assertEqual(row.target_name, "a gnoll")
        self.assertEqual(row.safe_remaining_seconds, 24)
        self.assertEqual(row.remaining_seconds, 30)
        self.assertEqual(tracker.snapshot(BASE + timedelta(seconds=2)).active_count, 1)
        self.assertIsNone(tracker.pending)

    def test_uncorrelated_or_mismatched_landing_is_ignored(self):
        tracker = MezTracker()
        self.assertIsNone(tracker.observe_landing("a gnoll", BASE))
        tracker.begin_cast("Mesmerize", BASE)
        self.assertIsNone(tracker.observe_landing(
            "a gnoll", BASE + timedelta(seconds=1), "Enthrall"))
        self.assertEqual(tracker.snapshot(BASE + timedelta(seconds=1)).active_count, 0)

    def test_single_target_cast_accepts_only_one_landing(self):
        tracker = MezTracker()
        tracker.begin_cast("Enthrall", BASE)
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))
        self.assertIsNone(tracker.observe_landing(
            "an orc", BASE + timedelta(seconds=1)))
        self.assertEqual(tracker.snapshot(BASE + timedelta(seconds=1)).active_count, 1)

    def test_area_cast_accepts_multiple_landings_and_groups_identical_names(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerization", BASE)
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))
        tracker.observe_landing("an orc", BASE + timedelta(seconds=1))

        snapshot = tracker.snapshot(BASE + timedelta(seconds=2))
        self.assertEqual(snapshot.group_count, 2)
        self.assertEqual(snapshot.active_count, 3)
        by_name = {row.target_name: row for row in snapshot.rows}
        self.assertEqual(by_name["a gnoll"].count, 2)
        self.assertEqual(by_name["a gnoll"].safe_remaining_seconds, 23)
        self.assertEqual(by_name["a gnoll"].remaining_seconds, 29)

    def test_ranked_duration_begins_at_landing_time(self):
        tracker = MezTracker()
        tracker.begin_cast("Enthrall II", BASE)
        landed = BASE + timedelta(seconds=3)
        tracker.observe_landing("a froglok", landed)
        row = tracker.snapshot(landed + timedelta(seconds=7)).rows[0]
        self.assertEqual(row.duration_seconds, 60)
        self.assertEqual(row.safe_expires_at, landed + timedelta(seconds=60))
        self.assertEqual(row.expires_at, landed + timedelta(seconds=66))
        self.assertEqual(row.safe_remaining_seconds, 53)
        self.assertEqual(row.remaining_seconds, 59)

    def test_current_eql_server_expiry_phase_is_one_tick_after_safe_time(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerization V", BASE)
        tracker.observe_landing("Guard Tolax", BASE)

        safe_edge = tracker.snapshot(BASE + timedelta(seconds=36)).rows[0]
        self.assertTrue(safe_edge.last_tick)
        self.assertEqual(safe_edge.safe_remaining_seconds, 0)
        self.assertEqual(safe_edge.remaining_seconds, 6)
        self.assertEqual(
            tracker.snapshot(BASE + timedelta(seconds=42)).active_count, 1)
        self.assertEqual(
            tracker.snapshot(BASE + timedelta(seconds=43.25)).active_count, 0)

    def test_fizzle_and_interrupt_cancel_pending_casts(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerize", BASE)
        self.assertTrue(tracker.observe_fizzle())
        self.assertIsNone(tracker.pending)
        tracker.begin_cast("Enthrall", BASE)
        self.assertTrue(tracker.observe_interrupt())
        self.assertIsNone(tracker.pending)

    def test_a_new_unknown_own_cast_closes_an_old_pending_episode(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerize", BASE)
        self.assertIsNone(tracker.begin_cast(
            "Tashani", BASE + timedelta(seconds=1)))
        self.assertIsNone(tracker.observe_landing(
            "a gnoll", BASE + timedelta(seconds=2)))

    def test_resist_cancels_single_but_not_whole_area_cast(self):
        single = MezTracker()
        single.begin_cast("Mesmerize", BASE)
        self.assertTrue(single.observe_resist(occurred_at=BASE + timedelta(seconds=1)))
        self.assertIsNone(single.observe_landing(
            "a gnoll", BASE + timedelta(seconds=1)))

        area = MezTracker()
        area.begin_cast("Mesmerization", BASE)
        self.assertFalse(area.observe_resist(
            "Mesmerization", BASE + timedelta(seconds=1)))
        self.assertIsNotNone(area.observe_landing(
            "a gnoll", BASE + timedelta(seconds=1)))

    def test_pending_and_area_landing_windows_expire(self):
        tracker = MezTracker(pending_seconds=4, area_landing_seconds=2)
        tracker.begin_cast("Mesmerize", BASE)
        self.assertIsNone(tracker.observe_landing(
            "too late", BASE + timedelta(seconds=5)))

        tracker.begin_cast("Mesmerization", BASE + timedelta(seconds=10))
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=11))
        self.assertIsNone(tracker.observe_landing(
            "an orc", BASE + timedelta(seconds=14)))

    def test_spell_aware_correlation_rejects_a_late_nearby_landing(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerize", BASE)
        self.assertIsNone(tracker.observe_landing(
            "a groupmate's target", BASE + timedelta(seconds=5)))


class MezLifecycleTests(unittest.TestCase):
    def test_recast_refreshes_instead_of_duplicating_single_target(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerize", BASE)
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))
        tracker.begin_cast("Enthrall", BASE + timedelta(seconds=10))
        tracker.observe_landing("A GNOLL", BASE + timedelta(seconds=11))

        snapshot = tracker.snapshot(BASE + timedelta(seconds=11))
        self.assertEqual(snapshot.active_count, 1)
        row = snapshot.rows[0]
        self.assertEqual(row.spell_name, "Enthrall")
        self.assertEqual(row.safe_remaining_seconds, 48)
        self.assertEqual(row.remaining_seconds, 54)

    def test_area_recast_refreshes_existing_group_before_adding_more(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerization", BASE)
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))

        tracker.begin_cast("Mesmerization", BASE + timedelta(seconds=10))
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=11))
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=11))
        snapshot = tracker.snapshot(BASE + timedelta(seconds=11))
        self.assertEqual(snapshot.active_count, 2)
        self.assertEqual(snapshot.rows[0].count, 2)
        self.assertEqual(snapshot.rows[0].safe_remaining_seconds, 24)
        self.assertEqual(snapshot.rows[0].remaining_seconds, 30)

    def test_damage_kill_and_fade_each_remove_their_distinct_target(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerization", BASE)
        for target in ("damage target", "kill target", "fade target"):
            tracker.observe_landing(target, BASE + timedelta(seconds=1))

        self.assertTrue(tracker.observe_damage(
            "damage target", BASE + timedelta(seconds=2)))
        self.assertEqual(tracker.snapshot(BASE + timedelta(seconds=2)).active_count, 2)
        self.assertTrue(tracker.observe_kill(
            "kill target", BASE + timedelta(seconds=3)))
        self.assertEqual(tracker.snapshot(BASE + timedelta(seconds=3)).active_count, 1)
        self.assertTrue(tracker.observe_fade(
            "fade target", BASE + timedelta(seconds=4), "Mesmerization"))
        self.assertEqual(tracker.snapshot(BASE + timedelta(seconds=4)).active_count, 0)

    def test_one_wake_signal_chain_cannot_erase_same_named_twins(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerization", BASE)
        for _ in range(3):
            tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))

        wake_at = BASE + timedelta(seconds=2)
        self.assertTrue(tracker.observe_fade(
            "a gnoll", wake_at, "Mesmerization"))
        self.assertFalse(tracker.observe_damage("a gnoll", wake_at))
        self.assertFalse(tracker.observe_damage("a gnoll", wake_at))
        self.assertEqual(tracker.snapshot(wake_at).active_count, 2)
        # The death of that already-accounted-for awake instance also cannot
        # consume a controlled twin.
        self.assertFalse(tracker.observe_kill(
            "a gnoll", BASE + timedelta(seconds=3)))
        self.assertEqual(
            tracker.snapshot(BASE + timedelta(seconds=3)).active_count, 2)

    def test_remez_of_known_awake_twin_restores_group_count(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerization", BASE)
        for _ in range(3):
            tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))
        tracker.observe_fade(
            "a gnoll", BASE + timedelta(seconds=2), "Mesmerization")
        self.assertEqual(
            tracker.snapshot(BASE + timedelta(seconds=2)).active_count, 2)

        tracker.begin_cast("Mesmerize", BASE + timedelta(seconds=3))
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=4))
        snapshot = tracker.snapshot(BASE + timedelta(seconds=4))
        self.assertEqual(snapshot.active_count, 3)
        self.assertEqual(snapshot.rows[0].count, 3)

    def test_unknown_spell_fade_cannot_remove_a_timer(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerize", BASE)
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))
        self.assertFalse(tracker.observe_fade(
            "a gnoll", BASE + timedelta(seconds=2), "Tashani"))
        self.assertEqual(tracker.snapshot(BASE + timedelta(seconds=2)).active_count, 1)

    def test_unranked_fade_matches_the_base_name_of_a_ranked_cast(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerize V", BASE)
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))
        self.assertTrue(tracker.observe_fade(
            "a gnoll", BASE + timedelta(seconds=2), "Mesmerize"))
        self.assertEqual(tracker.snapshot(BASE + timedelta(seconds=2)).active_count, 0)

    def test_targetless_fade_removes_the_earliest_matching_timer(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerize", BASE)
        tracker.observe_landing("first", BASE + timedelta(seconds=1))
        tracker.begin_cast("Mesmerize", BASE + timedelta(seconds=2))
        tracker.observe_landing("second", BASE + timedelta(seconds=3))
        self.assertTrue(tracker.observe_fade(
            None, BASE + timedelta(seconds=4), "Mesmerize"))
        snapshot = tracker.snapshot(BASE + timedelta(seconds=4))
        self.assertEqual(snapshot.active_count, 1)
        self.assertEqual(snapshot.rows[0].target_name, "second")

    def test_expired_entries_are_pruned_and_clear_resets_everything(self):
        tracker = MezTracker()
        tracker.begin_cast("Entrancing Lights", BASE)
        tracker.observe_landing("a gnoll", BASE)
        last_tick = tracker.snapshot(BASE + timedelta(seconds=6))
        self.assertEqual(last_tick.active_count, 1)
        self.assertTrue(last_tick.rows[0].last_tick)
        self.assertEqual(last_tick.rows[0].safe_remaining_seconds, 0)
        self.assertEqual(tracker.snapshot(
            BASE + timedelta(seconds=13)).active_count, 1)
        self.assertEqual(tracker.snapshot(
            BASE + timedelta(seconds=13.25)).active_count, 0)

        tracker.begin_cast("Mesmerization", BASE + timedelta(seconds=10))
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=11))
        tracker.observe_landing("an orc", BASE + timedelta(seconds=11))
        self.assertEqual(tracker.clear(), 2)
        self.assertIsNone(tracker.pending)
        self.assertEqual(tracker.snapshot(BASE + timedelta(seconds=11)).active_count, 0)

    def test_snapshot_sorts_urgent_rows_and_reports_overflow(self):
        tracker = MezTracker()
        for offset, target in ((0, "third"), (2, "first"), (1, "second"), (3, "hidden")):
            at = BASE + timedelta(seconds=offset)
            tracker.begin_cast("Mesmerize", at)
            tracker.observe_landing(target, at)
        snapshot = tracker.snapshot(BASE, limit=3)
        self.assertEqual([row.target_name for row in snapshot.rows],
                         ["third", "second", "first"])
        self.assertEqual(snapshot.hidden_rows, 1)
        self.assertEqual(snapshot.group_count, 4)

    def test_warning_event_is_one_shot_and_refresh_rearms_it(self):
        tracker = MezTracker()
        tracker.begin_cast("Mesmerize", BASE)
        tracker.observe_landing("a gnoll", BASE)
        self.assertEqual(tracker.pop_warning_events(
            BASE + timedelta(seconds=13)), ())
        events = tracker.pop_warning_events(BASE + timedelta(seconds=14))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].remaining_seconds, 10)
        self.assertEqual(tracker.pop_warning_events(
            BASE + timedelta(seconds=15)), ())

        tracker.begin_cast("Mesmerize", BASE + timedelta(seconds=16))
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=16))
        self.assertEqual(len(tracker.pop_warning_events(
            BASE + timedelta(seconds=30))), 1)


class MezPresentationHelperTests(unittest.TestCase):
    def test_urgency_thresholds(self):
        self.assertEqual(mez_urgency(11), "safe")
        self.assertEqual(mez_urgency(10), "warning")
        self.assertEqual(mez_urgency(5), "critical")

    def test_remaining_time_format_rounds_up(self):
        self.assertEqual(format_mez_remaining(0), "0s")
        self.assertEqual(format_mez_remaining(0.1), "1s")
        self.assertEqual(format_mez_remaining(59.2), "60s")
        self.assertEqual(format_mez_remaining(60.1), "1:01")
        self.assertEqual(format_mez_remaining(0, last_tick=True), "LAST TICK")


if __name__ == "__main__":
    unittest.main()
