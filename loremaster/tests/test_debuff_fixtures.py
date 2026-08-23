"""Deterministic sanitized log replays for the debuff timer deck."""

import importlib.util
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))
SPEC = importlib.util.spec_from_file_location(
    "loremaster_debuff_fixture_app", LOREMASTER_DIR / "loremaster.py")
LOREMASTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LOREMASTER
SPEC.loader.exec_module(LOREMASTER)

from debuff_timer import DebuffTracker  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "debuff_sequences.json"
BASE = datetime(2026, 8, 6, 20, 0, 0)


class DebuffSequenceFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_schema_is_versioned(self):
        self.assertEqual(self.payload["schemaVersion"], 1)
        self.assertGreaterEqual(len(self.payload["sequences"]), 18)

    def test_every_sequence_replays_to_its_expected_deck(self):
        caster_level = int(self.payload.get("casterLevel", 50))
        for case in self.payload["sequences"]:
            with self.subTest(case=case["name"]):
                stats = LOREMASTER.SessionStats("Spin")
                stats.level = caster_level
                mez = LOREMASTER.MezTracker()
                tracker = DebuffTracker()
                tracker.set_caster_level(caster_level)

                for event in case["events"]:
                    stamp = (BASE + timedelta(seconds=event["at"])).strftime(
                        LOREMASTER.TS_FORMAT)
                    parsed = LOREMASTER.parse_line(f"[{stamp}] {event['line']}")
                    self.assertIsNotNone(
                        parsed, f"line did not parse: {event['line']}")
                    ts, kind, groups = parsed
                    LOREMASTER.apply_log_models(
                        stats, mez, ts, kind, groups,
                        debuff_tracker=tracker, caster_level=caster_level)

                snapshot = tracker.snapshot(
                    BASE + timedelta(seconds=case["observeAt"]),
                    limit=case.get("limit", 6))
                observed = sorted(
                    f"{group.target}|{row.spell}|{row.kind}|{row.duration_confidence}"
                    for group in snapshot.groups for row in group.rows)
                self.assertEqual(observed, sorted(case["expected"]["rows"]))
                self.assertEqual(snapshot.overflow,
                                 case["expected"].get("overflow", 0))


if __name__ == "__main__":
    unittest.main()
