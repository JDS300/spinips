import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from control_snapshot import merge_control_snapshots  # noqa: E402
from lull_timer import (  # noqa: E402
    LULL_SPELLS,
    LullTracker,
    duration_formula_ticks,
    resolve_lull_spell,
)
from mez_timer import MezTracker  # noqa: E402


BASE = datetime(2026, 8, 6, 12, 0, 0)


class LullSpellCatalogTests(unittest.TestCase):
    def test_supported_eql_spell_catalog(self):
        self.assertEqual({spell.name for spell in LULL_SPELLS}, {
            "Pacify", "Calm", "Lull", "Lull Animal", "Harmony",
            "Soothe", "Calm Animal", "Pacification",
        })

    def test_classic_duration_formulas_and_caps(self):
        self.assertEqual(duration_formula_ticks(2, 30), 20)
        self.assertEqual(duration_formula_ticks(8, 15), 25)
        self.assertEqual(duration_formula_ticks(9, 5), 20)
        self.assertEqual(resolve_lull_spell("Pacify").duration_ticks, 7)
        self.assertEqual(resolve_lull_spell("Pacify").duration_confidence,
                         "exact")
        low = resolve_lull_spell("Lull", caster_level=1)
        high = resolve_lull_spell("Lull", caster_level=50)
        self.assertEqual((low.duration_ticks, high.duration_ticks), (12, 20))
        self.assertEqual(high.safe_duration_seconds, 114)

    def test_unknown_level_is_conservative_and_rank_aware(self):
        lull = resolve_lull_spell("Lull V")
        self.assertEqual(lull.duration_confidence, "conservative")
        self.assertEqual(lull.duration_ticks, 18)
        self.assertEqual(lull.safe_duration_seconds, 102)
        self.assertAlmostEqual(lull.cast_seconds, 1.2)

    def test_unknown_and_non_lull_spells_do_not_resolve(self):
        self.assertIsNone(resolve_lull_spell("Mesmerize"))
        self.assertIsNone(resolve_lull_spell("Greater Healing"))
        self.assertIsNone(resolve_lull_spell(None))


class LullEvidenceTrackerTests(unittest.TestCase):
    def test_cast_alone_never_starts_a_timer(self):
        tracker = LullTracker()
        tracker.begin_cast("Calm", BASE, caster_level=50)
        self.assertEqual(tracker.snapshot(BASE).active_count, 0)
        snapshot = tracker.snapshot(BASE + timedelta(seconds=5))
        self.assertEqual(snapshot.active_count, 0)
        self.assertEqual(snapshot.notices[-1].status, "unconfirmed")

    def test_visible_landing_starts_exact_conservative_tick_timer(self):
        tracker = LullTracker()
        tracker.begin_cast("Calm V", BASE, caster_level=50)
        row = tracker.observe_landing("a soul carrier",
                                      BASE + timedelta(seconds=2))
        self.assertEqual(row.target_name, "a soul carrier")
        self.assertEqual(row.confidence, "exact")
        self.assertEqual(row.duration_seconds, 60)
        self.assertEqual(row.safe_remaining_seconds, 60)
        self.assertEqual(row.remaining_seconds, 66)

    def test_silent_spells_stay_explicitly_unconfirmed(self):
        tracker = LullTracker()
        tracker.begin_cast("Harmony", BASE, caster_level=50)
        snapshot = tracker.snapshot(BASE + timedelta(seconds=1))
        self.assertEqual(snapshot.active_count, 0)
        self.assertEqual(snapshot.notices[-1].status, "unconfirmed")
        self.assertIn("no landing line", snapshot.notices[-1].detail)

    def test_failure_paths_close_pending_without_false_timer(self):
        for method, detail in (
                ("observe_fizzle", "fizzled"),
                ("observe_interrupt", "interrupted")):
            with self.subTest(method=method):
                tracker = LullTracker()
                tracker.begin_cast("Calm", BASE, caster_level=50)
                getattr(tracker, method)(BASE + timedelta(seconds=1))
                snap = tracker.snapshot(BASE + timedelta(seconds=1))
                self.assertEqual(snap.active_count, 0)
                self.assertIn(detail, snap.notices[-1].detail)
        tracker = LullTracker()
        tracker.begin_cast("Calm", BASE, caster_level=50)
        tracker.observe_resist(BASE + timedelta(seconds=1), "Calm")
        self.assertEqual(
            tracker.snapshot(BASE + timedelta(seconds=1)).notices[-1].status,
            "failed",
        )

    def test_nearby_cast_ambiguity_is_visible_and_never_timed(self):
        tracker = LullTracker()
        tracker.observe_nearby_cast("Calm", BASE, caster_level=50)
        tracker.begin_cast("Calm", BASE + timedelta(seconds=1),
                           caster_level=50)
        self.assertIsNone(tracker.observe_landing(
            "a soul carrier", BASE + timedelta(seconds=2)))
        snapshot = tracker.snapshot(BASE + timedelta(seconds=2))
        self.assertEqual(snapshot.active_count, 0)
        self.assertTrue(any(notice.status == "ambiguous"
                            for notice in snapshot.notices))

    def test_damage_fade_overwrite_kill_and_clear_retire_state(self):
        operations = (
            lambda tracker, at: tracker.observe_damage("a gnoll", at),
            lambda tracker, at: tracker.observe_fade("a gnoll", at, "Calm"),
            lambda tracker, at: tracker.observe_overwrite(
                "a gnoll", at, "Calm"),
            lambda tracker, at: tracker.observe_kill("a gnoll", at),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                tracker = LullTracker()
                tracker.begin_cast("Calm", BASE, caster_level=50)
                tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))
                self.assertTrue(operation(tracker, BASE + timedelta(seconds=2)))
                self.assertEqual(tracker.snapshot(
                    BASE + timedelta(seconds=2)).active_count, 0)
        tracker = LullTracker()
        tracker.begin_cast("Calm", BASE, caster_level=50)
        tracker.observe_landing("a gnoll", BASE + timedelta(seconds=1))
        self.assertEqual(tracker.clear(), 1)

    def test_last_tick_warning_and_expiry_are_deterministic(self):
        tracker = LullTracker()
        tracker.begin_cast("Calm", BASE, caster_level=50)
        tracker.observe_landing("a gnoll", BASE)
        self.assertEqual(tracker.pop_warning_events(
            BASE + timedelta(seconds=25)), ())
        self.assertEqual(len(tracker.pop_warning_events(
            BASE + timedelta(seconds=26))), 1)
        self.assertTrue(tracker.snapshot(
            BASE + timedelta(seconds=36)).rows[0].last_tick)
        self.assertEqual(tracker.snapshot(
            BASE + timedelta(seconds=43)).active_count, 0)

    def test_merged_snapshot_keeps_active_timers_ahead_of_notices(self):
        mez = MezTracker()
        mez.begin_cast("Mesmerize", BASE)
        mez.observe_landing("a mezzed gnoll", BASE + timedelta(seconds=1))
        lull = LullTracker()
        lull.begin_cast("Harmony", BASE, caster_level=50)
        combined = merge_control_snapshots(
            mez.snapshot(BASE + timedelta(seconds=2)),
            lull.snapshot(BASE + timedelta(seconds=2)),
        )
        self.assertEqual(combined.rows[0].timer_state, "active")
        self.assertEqual(combined.rows[0].control_kind, "mez")
        self.assertEqual(combined.rows[1].timer_state, "unconfirmed")
        self.assertEqual(combined.notice_count, 1)


if __name__ == "__main__":
    unittest.main()
