"""Deterministic sanitized log replays for every control-state exit path."""

import importlib.util
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))
SPEC = importlib.util.spec_from_file_location(
    "loremaster_control_fixture_app", LOREMASTER_DIR / "loremaster.py")
LOREMASTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LOREMASTER
SPEC.loader.exec_module(LOREMASTER)

from control_snapshot import merge_control_snapshots  # noqa: E402
from engine_protocol import build_engine_snapshot, snapshot_event  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "control_sequences.json"
BASE = datetime(2026, 8, 6, 20, 0, 0)


class ControlSequenceFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_schema_is_versioned(self):
        self.assertEqual(self.payload["schemaVersion"], 1)
        self.assertGreaterEqual(len(self.payload["sequences"]), 18)

    def test_sanitized_sequences_have_deterministic_state_and_events(self):
        for sequence_index, case in enumerate(self.payload["sequences"], 1):
            with self.subTest(case=case["name"]):
                stats = LOREMASTER.SessionStats("Spin")
                stats.level = 50
                mez = LOREMASTER.MezTracker()
                lull = LOREMASTER.LullTracker()
                for event in case["events"]:
                    if event.get("action") in {"reset", "character_switch"}:
                        mez.clear()
                        lull.clear()
                        continue
                    at = BASE + timedelta(seconds=event["at"])
                    stamp = at.strftime(LOREMASTER.TS_FORMAT)
                    parsed = LOREMASTER.parse_line(
                        f"[{stamp}] {event['line']}")
                    self.assertIsNotNone(parsed, event["line"])
                    ts, kind, groups = parsed
                    LOREMASTER.apply_log_models(
                        stats, mez, ts, kind, groups,
                        lull_tracker=lull, caster_level=stats.level)
                observed = BASE + timedelta(seconds=case["observeAt"])
                mez_snapshot = mez.snapshot(observed, limit=None)
                lull_snapshot = lull.snapshot(observed, limit=None)
                combined = merge_control_snapshots(
                    mez_snapshot, lull_snapshot, limit=None)
                expected = case["expected"]
                self.assertEqual(mez_snapshot.active_count,
                                 expected["mezActive"])
                self.assertEqual(lull_snapshot.active_count,
                                 expected["lullActive"])
                states = [f"{row.control_kind}:{row.timer_state}"
                          for row in combined.rows]
                self.assertEqual(states, expected["controlStates"])

                runtime = stats.snapshot(observed)
                boundary = build_engine_snapshot(
                    sequence=sequence_index,
                    observed_at=observed.replace(tzinfo=timezone.utc),
                    stats_snapshot=runtime,
                    control_snapshot=combined,
                )
                encoded = snapshot_event(boundary).to_json()
                self.assertEqual(encoded, snapshot_event(boundary).to_json())
                self.assertEqual(json.loads(encoded)["sequence"],
                                 sequence_index)


if __name__ == "__main__":
    unittest.main()
