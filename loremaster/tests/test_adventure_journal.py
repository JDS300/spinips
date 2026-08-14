import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from adventure_journal import (  # noqa: E402
    AdventureJournal, SCHEMA_VERSION, normalize_item_key,
)


NOW = datetime(2026, 8, 13, 18, 30, tzinfo=timezone.utc)


class AdventureJournalTests(unittest.TestCase):
    def test_replayed_loot_and_encounter_are_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "journal.sqlite3"
            journal = AdventureJournal(path)
            try:
                first = journal.record_loot(
                    occurred_at=NOW, item="Cloak of Flames +4",
                    looter="Spin", source="Lord Nagafen", zone="Solusek B",
                    character="Spin", server="qeynos",
                    acquisition_type="corpse", evidence="same evidence")
                replay = journal.record_loot(
                    occurred_at=NOW, item="Cloak of Flames +4",
                    looter="Spin", source="Lord Nagafen", zone="Solusek B",
                    character="Spin", server="qeynos",
                    acquisition_type="corpse", evidence="same evidence")
                encounter = dict(
                    started_at=NOW, ended_at=NOW, name="Lord Nagafen",
                    character="Spin", server="qeynos", zone="Solusek B",
                    damage=1200, seconds=6, dps=200, kills=1)
                fight_first = journal.record_encounter(**encounter)
                fight_replay = journal.record_encounter(**encounter)
                counts = journal.counts()
            finally:
                journal.close()
            self.assertTrue(first.inserted)
            self.assertFalse(replay.inserted)
            self.assertEqual(first.record_id, replay.record_id)
            self.assertTrue(fight_first.inserted)
            self.assertFalse(fight_replay.inserted)
            self.assertEqual(counts, {"loot": 1, "encounters": 1})

    def test_item_cache_joins_base_name_and_keeps_ranked_display(self):
        with tempfile.TemporaryDirectory() as root:
            journal = AdventureJournal(Path(root) / "journal.sqlite3")
            try:
                journal.put_item_cache(
                    title="Cloak of Flames", url="https://eqlwiki.com/x",
                    stats={"AC": 10}, notes="Magic item",
                    sections={"Drops From": ["Lord Nagafen"]},
                    source="EQL Wiki", fetched_at=NOW)
                journal.record_loot(
                    occurred_at=NOW, item="Cloak of Flames +4",
                    character="Spin", evidence="ranked item")
                row = journal.recent_loot(character="Spin")[0]
            finally:
                journal.close()
            self.assertEqual(normalize_item_key(row["item"]), "cloak of flames")
            self.assertEqual(row["item"], "Cloak of Flames +4")
            self.assertEqual(row["item_info"]["stats"], {"AC": 10})

    def test_schema_and_reads_are_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "journal.sqlite3"
            journal = AdventureJournal(path)
            try:
                for index in range(280):
                    journal.record_loot(
                        occurred_at=f"2026-08-13T18:{index // 60:02d}:{index % 60:02d}Z",
                        item=f"Item {index}", evidence=f"event {index}")
                rows = journal.recent_loot(limit=9999)
            finally:
                journal.close()
            connection = sqlite3.connect(path)
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(len(rows), 250)

    def test_durable_loot_query_filters_pages_and_joins_known_items(self):
        with tempfile.TemporaryDirectory() as root:
            journal = AdventureJournal(Path(root) / "journal.sqlite3")
            try:
                journal.put_item_cache(
                    title="Cloak of Flames", stats=["AC: 10"],
                    source="EQL Wiki", fetched_at=NOW)
                rows = (
                    ("Cloak of Flames +4", "Spin", "Nagafen's Lair", 4),
                    ("Ruby", "Groupmate", "Nagafen's Lair", 4),
                    ("Sapphire", "Spin", "The Nexus", None),
                )
                for index, (item, looter, zone, tier) in enumerate(rows):
                    journal.record_loot(
                        occurred_at=f"2026-08-13T18:30:0{index}Z",
                        item=item, looter=looter, zone=zone,
                        character="Spin", raid_tier=tier,
                        evidence=f"event {index}")
                known = journal.query_loot(
                    character="Spin", scope="known", query="cloak")
                others = journal.query_loot(
                    character="Spin", scope="others", zone="Nagafen's Lair",
                    raid_tier=4, limit=1)
                open_world = journal.query_loot(
                    character="Spin", scope="mine", raid_tier="open")
            finally:
                journal.close()
            self.assertEqual(known["total"], 1)
            self.assertEqual(known["rows"][0]["item_info"]["stats"], ["AC: 10"])
            self.assertEqual(others["total"], 1)
            self.assertEqual(others["rows"][0]["item"], "Ruby")
            self.assertFalse(others["has_more"])
            self.assertEqual(open_world["rows"][0]["item"], "Sapphire")

    def test_corrupt_database_is_quarantined_and_recreated(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "journal.sqlite3"
            corrupt_bytes = b"not a sqlite database\x00private evidence"
            path.write_bytes(corrupt_bytes)

            journal = AdventureJournal(path)
            try:
                write = journal.record_loot(
                    occurred_at=NOW, item="Recovered Item",
                    evidence="after recovery")
                counts = journal.counts()
                quarantine = journal.quarantined_path
                available = journal.available
            finally:
                journal.close()

            self.assertTrue(available)
            self.assertFalse(journal.degraded)
            self.assertTrue(write.inserted)
            self.assertEqual(counts, {"loot": 1, "encounters": 0})
            self.assertIsNotNone(quarantine)
            self.assertEqual(quarantine.read_bytes(), corrupt_bytes)
            self.assertTrue(path.exists())

    def test_newer_schema_is_never_quarantined_or_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "journal.sqlite3"
            connection = sqlite3.connect(path)
            try:
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
            finally:
                connection.close()

            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                AdventureJournal(path)

            connection = sqlite3.connect(path)
            try:
                version = connection.execute(
                    "PRAGMA user_version").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(version, SCHEMA_VERSION + 1)
            self.assertEqual(list(path.parent.glob("*.corrupt-*")), [])

    def test_runtime_database_error_degrades_to_safe_no_op(self):
        with tempfile.TemporaryDirectory() as root:
            journal = AdventureJournal(Path(root) / "journal.sqlite3")
            try:
                # Simulate a write failure without relying on platform-specific
                # filesystem permissions or locking behavior.
                journal._connection.execute("PRAGMA query_only = ON")
                write = journal.record_loot(
                    occurred_at=NOW, item="Unwritten Item",
                    evidence="forced failure")

                self.assertFalse(write.inserted)
                self.assertTrue(journal.degraded)
                self.assertFalse(journal.available)
                self.assertIn("attempt to write a readonly database",
                              journal.last_error)
                self.assertEqual(journal.recent_loot(), [])
                self.assertEqual(journal.recent_encounters(), [])
                self.assertEqual(journal.counts(), {
                    "loot": 0, "encounters": 0,
                })
                self.assertEqual(journal.loot_summary(), {
                    "events": 0, "quantity": 0, "unique_items": 0,
                })
                self.assertEqual(journal.put_item_cache(
                    title="Still Safe"), "still safe")
            finally:
                journal.close()


if __name__ == "__main__":
    unittest.main()
