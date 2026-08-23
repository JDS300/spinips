"""Debuff snapshot transport and settings plumbing."""

import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from control_snapshot import merge_control_snapshots  # noqa: E402
from debuff_timer import DebuffTracker  # noqa: E402
from engine_protocol import build_engine_snapshot, snapshot_event  # noqa: E402
from lull_timer import LullTracker  # noqa: E402
from mez_timer import MezTracker  # noqa: E402

BASE = datetime(2026, 8, 6, 19, 0, 0)


def at(seconds):
    return BASE + timedelta(seconds=seconds)


def loaded_tracker():
    tracker = DebuffTracker()
    tracker.set_caster_level(50)
    tracker.begin_cast("Togor's Insects", at(0))
    tracker.observe_landing("an ice giant", "yawns", at(1))
    tracker.begin_cast("Envenomed Bolt", at(2))
    tracker.observe_dot_tick("an ice giant", "Envenomed Bolt", at(8))
    return tracker


def payload_for(debuff_snapshot):
    controls = merge_control_snapshots(
        MezTracker().snapshot(at(10)), LullTracker().snapshot(at(10)))
    snapshot = build_engine_snapshot(
        sequence=1, observed_at=at(10), stats_snapshot={},
        control_snapshot=controls, debuff_snapshot=debuff_snapshot)
    event = snapshot_event(snapshot)
    return json.loads(event.to_json())["snapshot"]


class DebuffProtocolTests(unittest.TestCase):
    def test_snapshot_payload_carries_grouped_debuffs(self):
        snapshot = payload_for(loaded_tracker().snapshot(at(10)))
        self.assertEqual(snapshot["debuffs"]["overflow"], 0)
        group = snapshot["debuffs"]["groups"][0]
        self.assertEqual(group["target"], "an ice giant")
        self.assertEqual(len(group["rows"]), 2)

    def test_row_keys_are_camel_case(self):
        snapshot = payload_for(loaded_tracker().snapshot(at(10)))
        row = snapshot["debuffs"]["groups"][0]["rows"][0]
        self.assertEqual(
            set(row),
            {"spell", "kind", "rank", "expiresAt", "remainingSeconds",
             "urgency", "durationConfidence", "expired"})
        for key in row:
            self.assertNotIn("_", key, key)

    def test_confidence_travels_so_the_deck_can_mark_estimates(self):
        snapshot = payload_for(loaded_tracker().snapshot(at(10)))
        rows = {row["spell"]: row
                for row in snapshot["debuffs"]["groups"][0]["rows"]}
        self.assertEqual(rows["Togor's Insects"]["durationConfidence"],
                         "conservative")
        self.assertEqual(rows["Envenomed Bolt"]["durationConfidence"], "exact")

    def test_an_empty_tracker_still_produces_a_well_formed_deck(self):
        snapshot = payload_for(DebuffTracker().snapshot(at(10)))
        self.assertEqual(snapshot["debuffs"], {"groups": [], "overflow": 0})

    def test_a_missing_debuff_snapshot_does_not_break_the_payload(self):
        """Older callers pass no debuff snapshot at all."""
        snapshot = payload_for(None)
        self.assertEqual(snapshot["debuffs"], {"groups": [], "overflow": 0})

    def test_overflow_is_reported(self):
        tracker = DebuffTracker()
        tracker.set_caster_level(50)
        for index in range(9):
            tracker.begin_cast("Envenomed Bolt", at(index))
            tracker.observe_dot_tick(f"mob {index}", "Envenomed Bolt",
                                     at(index + 0.5))
        snapshot = payload_for(tracker.snapshot(at(9), limit=6))
        self.assertEqual(len(snapshot["debuffs"]["groups"]), 6)
        self.assertEqual(snapshot["debuffs"]["overflow"], 3)


class DebuffSettingsTests(unittest.TestCase):
    def worker(self):
        """A HeadlessEngine with only the alert config a settings push needs."""
        import desktop_worker
        engine = desktop_worker.HeadlessEngine.__new__(
            desktop_worker.HeadlessEngine)
        engine.alert_config = {
            "alert_seconds": 6, "big_hit_threshold": 800,
            "mez_warning_seconds": 10, "lull_warning_seconds": 12,
            "debuff_timers_enabled": True, "debuff_dot_enabled": True,
            "debuff_slow_enabled": True, "debuff_resist_enabled": True,
            "debuff_warning_seconds": 10, "debuff_mob_limit": 6}
        return engine

    def test_debuff_settings_survive_the_alert_whitelist(self):
        worker = self.worker()
        worker.set_alert_config({
            "debuffTimersEnabled": True,
            "debuffSlowEnabled": False,
            "debuffWarningSeconds": 15,
            "debuffMobLimit": 3})
        self.assertIs(worker.alert_config["debuff_timers_enabled"], True)
        self.assertIs(worker.alert_config["debuff_slow_enabled"], False)
        self.assertEqual(worker.alert_config["debuff_warning_seconds"], 15)
        self.assertEqual(worker.alert_config["debuff_mob_limit"], 3)

    def test_out_of_range_settings_are_clamped(self):
        worker = self.worker()
        worker.set_alert_config({"debuffWarningSeconds": 999,
                                 "debuffMobLimit": 0})
        self.assertEqual(worker.alert_config["debuff_warning_seconds"], 30)
        self.assertEqual(worker.alert_config["debuff_mob_limit"], 1)

    def test_kind_toggles_filter_the_deck(self):
        tracker = loaded_tracker()
        snapshot = tracker.snapshot(at(10), kinds=frozenset({"slow"}))
        rows = [row.spell for group in snapshot.groups for row in group.rows]
        self.assertEqual(rows, ["Togor's Insects"])

    def test_the_master_toggle_empties_the_deck(self):
        tracker = loaded_tracker()
        self.assertEqual(tracker.snapshot(at(10), kinds=frozenset()).groups, ())


if __name__ == "__main__":
    unittest.main()
