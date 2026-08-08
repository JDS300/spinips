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
            "auto_attack": True,
            "fight": {"name": "an abhorrent", "dps": 284, "damage": 1700,
                      "charmed_pet_damage": 700, "seconds": 6},
            "fight_sources": {"Melee": {"t": 1000, "h": 5, "max": 240},
                              "Pet (an abhorrent)": {"t": 700, "h": 4, "max": 190}},
            "fight_targets": {"a soul carrier": 1700},
            "session_dps": 211,
            "personal_damage": 1000,
            "charmed_pet_damage": 700,
            "summoned_pet_damage": 0,
            "combat_damage": 1700,
            "combat_seconds": 6,
            "actor_damage": {
                "Spin": {"t": 1000, "h": 5, "max": 240},
                "an abhorrent (pet)": {"t": 700, "h": 4, "max": 190},
            },
            "actor_roles": {"Spin": "self", "an abhorrent (pet)": "charmed"},
        }
        runtime["fights"] = [{
            **runtime["fight"], "start": NOW, "end": NOW,
            "sources": runtime["fight_sources"],
            "targets": runtime["fight_targets"],
            "actor_damage": runtime["actor_damage"],
            "actor_roles": runtime["actor_roles"],
            "healing_done": 450, "heals_received": 320,
            "healing_sources": {
                "Superior Healing": {"t": 450, "h": 2, "max": 260, "over": 55},
            },
            "timeline": {
                0: {"out": 500, "in": 120, "heal": 200, "kills": 0},
                1: {"out": 1200, "in": 300, "heal": 250, "kills": 1},
            },
        }]
        runtime["timeline_bucket_seconds"] = 2
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
        self.assertTrue(decoded["snapshot"]["combat"]["autoAttack"])
        self.assertEqual(decoded["snapshot"]["combat"]["fightPersonalDamage"],
                         1000)
        self.assertEqual(decoded["snapshot"]["breakdown"]["sources"][0]["name"],
                         "Melee")
        encounter = decoded["snapshot"]["encounters"][0]
        self.assertEqual(encounter["personalDamage"], 1000)
        pet = next(row for row in encounter["actors"]
                   if row["role"] == "charmed")
        self.assertEqual(pet["encounterDps"], 117)
        self.assertEqual(pet["sessionDamage"], 700)
        self.assertEqual(encounter["healsReceived"], 320)
        self.assertEqual(encounter["healingSources"][0]["overheal"], 55)
        self.assertEqual(encounter["timeline"][1], {
            "second": 2, "outgoing": 1200, "incoming": 300,
            "healing": 250, "kills": 1,
        })

    def test_desktop_boundary_retains_sixty_fights(self):
        controls = merge_control_snapshots(
            MezTracker().snapshot(NOW), LullTracker().snapshot(NOW))
        fights = [{
            "name": f"target {index}", "damage": index + 1,
            "seconds": 1, "start": NOW, "end": NOW,
        } for index in range(75)]
        snapshot = build_engine_snapshot(
            sequence=1, observed_at=NOW,
            stats_snapshot={"character": "Spin", "fights": fights},
            control_snapshot=controls)
        self.assertEqual(len(snapshot.encounters), 60)
        self.assertEqual(snapshot.encounters[0].name, "target 15")
        self.assertEqual(snapshot.encounters[-1].name, "target 74")

    def test_long_encounter_timeline_is_compacted_without_losing_totals(self):
        controls = merge_control_snapshots(
            MezTracker().snapshot(NOW), LullTracker().snapshot(NOW))
        points = {
            index: {"out": index + 1, "in": 2, "heal": 3,
                    "kills": index % 47 == 0}
            for index in range(500)
        }
        fight = {
            "name": "long fight", "damage": 125250, "seconds": 1000,
            "start": NOW, "end": NOW, "timeline": points,
        }
        snapshot = build_engine_snapshot(
            sequence=1, observed_at=NOW,
            stats_snapshot={"character": "Spin", "fights": [fight],
                            "timeline_bucket_seconds": 2},
            control_snapshot=controls)
        timeline = snapshot.encounters[0].timeline

        self.assertLessEqual(len(timeline), 180)
        self.assertEqual(sum(row["out"] for row in points.values()),
                         sum(row.outgoing for row in timeline))
        self.assertEqual(sum(row["in"] for row in points.values()),
                         sum(row.incoming for row in timeline))
        self.assertEqual(sum(row["heal"] for row in points.values()),
                         sum(row.healing for row in timeline))
        self.assertEqual(sum(int(row["kills"]) for row in points.values()),
                         sum(row.kills for row in timeline))

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
