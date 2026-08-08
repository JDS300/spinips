import sys
import unittest
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from hover_ocr import OcrLine  # noqa: E402
from instance_lockout_ocr import (  # noqa: E402
    parse_instance_character, parse_instance_lockouts)


class InstanceLockoutOcrTests(unittest.TestCase):
    def test_reads_character_from_instance_leader_without_confusing_options(self):
        lines = [
            OcrLine("Leader: Spin", 20, 10, 100, 14),
            OcrLine("Leader Options:", 20, 300, 110, 14),
            OcrLine("Player Targeted:", 20, 320, 120, 14),
        ]
        self.assertEqual(parse_instance_character(lines), "Spin")

    def test_parses_only_tracked_difficulty_lockouts_from_merged_rows(self):
        lines = [
            OcrLine("Lockout Time Instance Name Event Name", 20, 10, 520, 14),
            OcrLine("0d:18h:54m:19s The Plane of Fear - Solo 2 (Adaptive) Replay Timer", 20, 40, 520, 14),
            OcrLine("2d:17h:54m:19s Nagafen's Lair - Group 3 (Fused) Magus Rokyl", 20, 60, 520, 14),
            OcrLine("2d:17h:54m:19s Nagafen's Lair - Group 3 (Fused) Lord Nagafen", 20, 80, 520, 14),
            OcrLine("2d:17h:54m:19s The Plane of Hate - Solo 4 (Refined) Innoruuk", 20, 100, 520, 14),
            OcrLine("2d:17h:54m:19s The Plane of Fear - Group 0 (Normal) Cazic-Thule", 20, 120, 520, 14),
        ]
        rows = parse_instance_lockouts(lines)
        self.assertEqual(
            [(row.target, row.difficulty) for row in rows],
            [("Cazic-Thule", 0), ("Innoruuk", 4), ("Lord Nagafen", 3)],
        )
        self.assertEqual(rows[-1].remaining_seconds, 2 * 86400 + 17 * 3600 + 54 * 60 + 19)

    def test_joins_separate_table_cells_and_tolerates_ocr_zeroes(self):
        lines = [
            OcrLine("Od:18h:O4m:19s", 10, 50, 100, 13),
            OcrLine("Permafrost Keep - Group 2 (Adaptive)", 130, 51, 250, 13),
            OcrLine("Lady Vox", 405, 50, 90, 13),
        ]
        rows = parse_instance_lockouts(lines)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].target, "Lady Vox")
        self.assertEqual(rows[0].difficulty, 2)
        self.assertEqual(rows[0].remaining_seconds, 18 * 3600 + 4 * 60 + 19)

    def test_conservative_name_matching_accepts_minor_event_ocr_error(self):
        rows = parse_instance_lockouts([
            OcrLine("2d:01h:02m:03s The Hole - Solo 1 (Normal) Master Yae1", 10, 20, 500, 14),
        ])
        self.assertEqual([(row.target, row.difficulty) for row in rows], [("Master Yael", 1)])


if __name__ == "__main__":
    unittest.main()
