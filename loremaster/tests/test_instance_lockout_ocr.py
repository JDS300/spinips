import os
import sys
import unittest
from difflib import SequenceMatcher
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hover_ocr  # noqa: E402
from hover_ocr import OcrLine  # noqa: E402
from instance_lockout_ocr import (  # noqa: E402
    parse_instance_character, parse_instance_lockouts)
# The X11 window helper lives beside the backend it exercises; reusing it keeps
# one definition of "a real window with known text".
from test_linux_capture import (  # noqa: E402
    ENGLISH_READY, X11_READY, _KnownTextWindow)


class InstanceLockoutOcrTests(unittest.TestCase):
    def test_reads_character_from_instance_leader_without_confusing_options(self):
        lines = [
            OcrLine("Leader: Spin", 20, 10, 100, 14),
            OcrLine("Leader Options:", 20, 300, 110, 14),
            OcrLine("Player Targeted:", 20, 320, 120, 14),
        ]
        self.assertEqual(parse_instance_character(lines), "Spin")

    def test_reads_character_when_windows_ocr_drops_leader_colon(self):
        lines = [
            OcrLine("Leader", 20, 10, 50, 14),
            OcrLine("Spin", 90, 10, 45, 14),
            OcrLine("Leader Options:", 20, 300, 110, 14),
        ]
        self.assertEqual(parse_instance_character(lines), "Spin")

    def test_blank_leader_does_not_borrow_distant_interface_text(self):
        lines = [
            OcrLine("Leader", 35, 56, 42, 12),
            OcrLine("Min Players: 1", 402, 56, 92, 12),
            OcrLine("Invite", 36, 727, 48, 12),
            OcrLine("Raid", 292, 727, 35, 12),
        ]
        self.assertEqual(parse_instance_character(lines), "")

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

    def test_accepts_hyphenated_timer_separator_from_compact_red_text(self):
        rows = parse_instance_lockouts([
            OcrLine("2d:15h-41 m:44s", 29, 306, 89, 10),
            OcrLine("Nagafen's Lair - Group 0 (Normal)", 130, 306, 185, 12),
            OcrLine("Lord Nagafen", 392, 306, 74, 12),
        ])
        self.assertEqual([(row.target, row.difficulty) for row in rows],
                         [("Lord Nagafen", 0)])
        self.assertEqual(rows[0].remaining_seconds,
                         2 * 86400 + 15 * 3600 + 41 * 60 + 44)

    def test_recovers_one_missing_timer_cell_from_immediately_adjacent_row(self):
        lines = [
            OcrLine("2d:15h-41 m:44s", 29, 306, 89, 10),
            OcrLine("Nagafen's Lair - Group 0 (Normal)", 130, 306, 185, 12),
            OcrLine("Lord Nagafen", 392, 306, 74, 12),
            OcrLine("The Permafrost Caverns - Solo 3 (Fused)", 130, 321, 195, 12),
            OcrLine("Lady Vox", 405, 321, 48, 12),
        ]
        rows = parse_instance_lockouts(lines)
        self.assertEqual(
            [(row.target, row.difficulty) for row in rows],
            [("Lady Vox", 3), ("Lord Nagafen", 0)],
        )
        self.assertTrue(all(
            row.remaining_seconds == 2 * 86400 + 15 * 3600 + 41 * 60 + 44
            for row in rows))

    def test_keeps_weekly_evidence_without_guessing_a_distant_timer(self):
        rows = parse_instance_lockouts([
            OcrLine("2d:15h-41 m:44s", 29, 306, 89, 10),
            OcrLine("The Permafrost Caverns - Solo 3 (Fused)", 130, 336, 195, 12),
            OcrLine("Lady Vox", 405, 336, 48, 12),
        ])
        self.assertEqual([(row.target, row.difficulty) for row in rows],
                         [("Lady Vox", 3)])
        self.assertIsNone(rows[0].remaining_seconds)

    def test_screenshot_cazic_d1_survives_missing_timer_and_event_ocr(self):
        rows = parse_instance_lockouts([
            # Exact geometry and OCR text reproduced from the reported Alt+Z
            # capture. Windows OCR omitted the entire compact timer column.
            OcrLine("The Plane of Fear - Group 1", 137.5, 603.5, 181, 11.5),
            OcrLine("cauc- I nule", 405, 605, 70, 8),
        ])
        self.assertEqual([(row.target, row.difficulty) for row in rows],
                         [("Cazic-Thule", 1)])
        self.assertIsNone(rows[0].remaining_seconds)

    def test_conservative_name_matching_accepts_minor_event_ocr_error(self):
        rows = parse_instance_lockouts([
            OcrLine("2d:01h:02m:03s The Hole - Solo 1 (Normal) Master Yae1", 10, 20, 500, 14),
        ])
        self.assertEqual([(row.target, row.difficulty) for row in rows], [("Master Yael", 1)])


@unittest.skipUnless(
    os.environ.get("LOREMASTER_X11_WINDOW_TESTS") == "1",
    "set LOREMASTER_X11_WINDOW_TESTS=1 to run tests that open a window")
@unittest.skipUnless(
    X11_READY and ENGLISH_READY,
    "the Alt+Z round trip requires X11 and tesseract's eng model: the parser "
    "keys on the literal word Group, and a substitute Latin model reads it as "
    "'Broup', which must not be taught to the parser")
class LinuxBackendRoundTripTests(unittest.TestCase):
    """Proof that the Linux capture/OCR backend feeds this parser real rows."""

    # No timer column is drawn on purpose. The only core X font a test rig can
    # rely on is 6x13, whose digits are genuinely ambiguous at that size in any
    # upscale ("14m" recognizes as "idm", "54m" as "Sdm", ":5" as "tS"), and
    # EverQuest does not use that font. Asserting around those confusions would
    # teach the parser about the rig, and hunting for digits that happen to
    # survive would be flaky, so this exercises the same missing-timer shape a
    # real capture already produces and leaves the compact timer column to the
    # in-game check.
    ROW = ("Nagafen's Lair - Group 3 (Fused) Lord Nagafen", "Leader: Spin")

    def test_a_rendered_lockout_row_survives_capture_ocr_and_parsing(self):
        import linux_capture

        with _KnownTextWindow(width=760, height=200, lines=self.ROW) as target:
            region = linux_capture.capture_window_region(
                target.window, hover_ocr.ROI_WIDTH, hover_ocr.ROI_HEIGHT,
                expected_process=linux_capture.process_identity(
                    os.getpid()).comm,
                cursor=(0, 0))
        recognized = linux_capture.recognize_lines(
            region.pixels, region.region_width, region.region_height,
            region.stride, scale=hover_ocr.OCR_SCALE)
        lines = [OcrLine(text=row.text, x=row.x, y=row.y,
                         width=row.width, height=row.height)
                 for row in recognized]
        rows = parse_instance_lockouts(lines)
        self.assertEqual([(row.target, row.difficulty) for row in rows],
                         [("Lord Nagafen", 3)],
                         msg=f"OCR returned {[line.text for line in lines]!r}")
        # No timer was drawn, so none may be invented from the rest of the row.
        self.assertIsNone(rows[0].remaining_seconds)
        # target/difficulty above are the values the ledger acts on, and they
        # are resolved against the catalog with SequenceMatcher, so they are
        # required to be exact. instance_name is raw recognized text with no
        # such resolution behind it, and the 6x13 rig font confuses letters as
        # readily as digits -- stock eng traineddata reads this row's "N" as
        # "M". Requiring it exactly would assert which traineddata build is
        # installed rather than anything about the parser.
        self.assertGreaterEqual(
            SequenceMatcher(None, rows[0].instance_name.casefold(),
                            "nagafen's lair").ratio(), 0.8,
            msg=f"instance name read as {rows[0].instance_name!r}")
        self.assertEqual(parse_instance_character(lines), "Spin")


if __name__ == "__main__":
    unittest.main()
