import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from weekly_tracker import RAID_TARGETS, WeeklyBossTracker, week_start  # noqa: E402


class WeeklyTrackerTests(unittest.TestCase):
    def test_week_boundary_is_tuesday_eight_pacific(self):
        pacific = ZoneInfo("America/Los_Angeles")
        before = datetime(2026, 8, 11, 7, 59, tzinfo=pacific)
        after = datetime(2026, 8, 11, 8, 1, tzinfo=pacific)
        self.assertEqual(week_start(before), datetime(2026, 8, 4, 8, tzinfo=pacific))
        self.assertEqual(week_start(after), datetime(2026, 8, 11, 8, tzinfo=pacific))

    def test_non_sky_catalog_contains_six_classic_raids(self):
        names = {target.name for target in RAID_TARGETS}
        self.assertEqual(len(names), 6)
        self.assertIn("Lord Nagafen", names)
        self.assertIn("Cazic-Thule", names)
        self.assertFalse(any("Sky" in target.zone for target in RAID_TARGETS))

    def test_difficulties_are_independent_and_persisted(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "weekly.json"
            tracker = WeeklyBossTracker(storage_path=path)
            now = datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)
            self.assertFalse(tracker.observe_kill(
                now, "a soul carrier", zone="Plane of Sky",
                character="Spin", difficulty=0))
            self.assertTrue(tracker.observe_kill(
                now, "Nagafen", zone="Nagafen's Lair",
                character="Spin", difficulty=0, duration_seconds=95.0))
            self.assertFalse(tracker.observe_kill(
                now, "Lord Nagafen", zone="Nagafen's Lair",
                character="Spin", difficulty=0))
            self.assertTrue(tracker.observe_kill(
                now, "Lord Nagafen", zone="Nagafen's Lair",
                character="Spin", difficulty=4, duration_seconds=140.0))
            restored = WeeklyBossTracker(storage_path=path)
            snapshot = restored.snapshot(now, character="Spin")
            nagafen = next(row for row in snapshot["raids"]
                           if row["target"] == "Lord Nagafen")
            self.assertEqual(snapshot["completedCount"], 2)
            self.assertEqual(snapshot["trackedLockoutCount"], 30)
            self.assertEqual(nagafen["difficulties"], [True, False, False, False, True])
            self.assertEqual(nagafen["bestSeconds"], [95.0, None, None, None, 140.0])
            self.assertEqual(json.loads(path.read_text())["schemaVersion"], 3)

    def test_log_instance_evidence_round_trips_and_schema_two_remains_readable(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "weekly.json"
            now = datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)
            tracker = WeeklyBossTracker(storage_path=path)
            self.assertTrue(tracker.observe_kill(
                now, "Lord Nagafen", zone="Nagafen's Lair",
                character="Spin", difficulty=4,
                difficulty_source="log-zone",
                instance_name="Nagafen's Lair - Solo 4 (Refined)",
                instance_mode="Solo", instance_label="Refined",
                context_observed_at="2026-08-07T19:55:00Z",
                evidence="You have entered Nagafen's Lair - Solo 4 (Refined)."))
            restored = WeeklyBossTracker(storage_path=path)
            kill = restored.snapshot(now, character="Spin")["kills"][0]
            self.assertEqual(kill["difficulty_source"], "log-zone")
            self.assertEqual(kill["instance_name"],
                             "Nagafen's Lair - Solo 4 (Refined)")
            self.assertEqual(kill["instance_label"], "Refined")

            legacy_path = Path(root) / "weekly-v2.json"
            legacy_path.write_text(json.dumps({
                "schemaVersion": 2,
                "kills": [{
                    "target": "Lady Vox", "zone": "Permafrost Keep",
                    "character": "Spin", "killed_at": "2026-08-07T20:00:00Z",
                    "difficulty": 2, "duration_seconds": 90.0,
                }],
            }), encoding="utf-8")
            legacy = WeeklyBossTracker(storage_path=legacy_path)
            legacy_kill = legacy.snapshot(now, character="Spin")["kills"][0]
            self.assertEqual(legacy_kill["difficulty"], 2)
            self.assertEqual(legacy_kill["difficulty_source"], "manual")

    def test_character_filter_and_manual_correction(self):
        tracker = WeeklyBossTracker()
        now = datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)
        self.assertTrue(tracker.set_completion(
            now, "Lady Vox", 2, character="Spin", completed=True))
        self.assertEqual(tracker.snapshot(now, character="Spin")["completedCount"], 1)
        self.assertEqual(tracker.snapshot(now, character="Other")["completedCount"], 0)
        self.assertTrue(tracker.set_completion(
            now, "Lady Vox", 2, character="Spin", completed=False))
        self.assertEqual(tracker.snapshot(now, character="Spin")["completedCount"], 0)


if __name__ == "__main__":
    unittest.main()
