import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from control_snapshot import merge_control_snapshots  # noqa: E402
from engine_protocol import (  # noqa: E402
    PROTOCOL_VERSION,
    build_engine_snapshot,
    snapshot_event,
)
from lull_timer import LullTracker  # noqa: E402
from mez_timer import MezTracker  # noqa: E402


NOW = datetime(2026, 8, 6, 18, 30, tzinfo=timezone.utc)


class EngineProtocolTests(unittest.TestCase):
    def test_versioned_snapshot_is_deterministic_and_json_safe(self):
        mez = MezTracker()
        mez.begin_cast("Mesmerize V", NOW)
        mez.observe_landing("a soul carrier", NOW)
        lull = LullTracker()
        controls = merge_control_snapshots(
            mez.snapshot(NOW), lull.snapshot(NOW), limit=None)
        runtime = {
            "character": "Spin",
            "level": 50,
            "composition": "PAL/MNK/ENC",
            "zone": "The Plane of Sky",
            "in_combat": True,
            "fight": {"name": "an abhorrent", "dps": 284, "damage": 1700,
                      "charmed_pet_damage": 700, "seconds": 6},
            "fight_sources": {"Melee": {"t": 1000, "h": 5, "max": 240},
                              "Pet (an abhorrent)": {"t": 700, "h": 4, "max": 190}},
            "fight_targets": {"a soul carrier": 1700},
            "session_dps": 211,
            "personal_damage": 1000,
            "charmed_pet_damage": 700,
            "summoned_pet_damage": 0,
        }
        snapshot = build_engine_snapshot(
            sequence=7, observed_at=NOW,
            stats_snapshot=runtime, control_snapshot=controls)
        event = snapshot_event(snapshot)
        first = event.to_json()
        second = snapshot_event(build_engine_snapshot(
            sequence=7, observed_at=NOW,
            stats_snapshot=dict(runtime), control_snapshot=controls)).to_json()
        self.assertEqual(first, second)
        decoded = json.loads(first)
        self.assertEqual(decoded["protocolVersion"], PROTOCOL_VERSION)
        self.assertEqual(decoded["eventType"], "engine.snapshot")
        self.assertEqual(decoded["snapshot"]["controls"][0]["kind"], "mez")
        self.assertEqual(decoded["snapshot"]["combat"]["charmedPetDamage"],
                         700)
        self.assertEqual(decoded["snapshot"]["combat"]["fightPersonalDamage"],
                         1000)
        self.assertEqual(decoded["snapshot"]["breakdown"]["sources"][0]["name"],
                         "Melee")

    def test_snapshot_copies_mutable_runtime_state(self):
        runtime = {"character": "Spin", "fight": {"dps": 50}}
        controls = merge_control_snapshots(
            MezTracker().snapshot(NOW), LullTracker().snapshot(NOW))
        snapshot = build_engine_snapshot(
            sequence=1, observed_at=NOW,
            stats_snapshot=runtime, control_snapshot=controls)
        runtime["character"] = "Changed"
        runtime["fight"]["dps"] = 999
        self.assertEqual(snapshot.character.name, "Spin")
        self.assertEqual(snapshot.combat.fight_dps, 50)


if __name__ == "__main__":
    unittest.main()
