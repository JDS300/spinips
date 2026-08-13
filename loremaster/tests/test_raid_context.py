import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from raid_context import (DIFFICULTY_LABELS, RaidContextTracker,  # noqa: E402
                          parse_raid_instance)


class RaidContextTests(unittest.TestCase):
    def test_exact_solo_and_group_names_map_all_five_difficulties(self):
        for difficulty, label in enumerate(DIFFICULTY_LABELS):
            for mode in ("Solo", "Group"):
                with self.subTest(difficulty=difficulty, mode=mode):
                    name = f"Nagafen's Lair - {mode} {difficulty} ({label})"
                    context = parse_raid_instance(
                        name,
                        occurred_at=datetime(
                            2026, 8, 8, 20, 0, tzinfo=timezone.utc),
                        evidence=f"You have entered {name}.")
                    self.assertIsNotNone(context)
                    assert context is not None
                    self.assertEqual(context.zone, "Nagafen's Lair")
                    self.assertEqual(context.mode, mode)
                    self.assertEqual(context.difficulty, difficulty)
                    self.assertEqual(context.label, label)
                    self.assertEqual(context.snapshot()["difficultyName"],
                                     f"D{difficulty}")

    def test_numeric_tier_and_label_must_agree(self):
        self.assertIsNone(parse_raid_instance(
            "The Plane of Fear - Group 1 (Refined)"))
        self.assertIsNone(parse_raid_instance(
            "The Plane of Fear - Group 7 (Refined)"))
        self.assertIsNone(parse_raid_instance(
            "The Plane of Fear - Raid 4 (Refined)"))

    def test_suffix_only_solo_and_group_are_direct_d0_evidence(self):
        for mode in ("Solo", "Group"):
            with self.subTest(mode=mode):
                name = f"The Plane of Fear - {mode}"
                context = parse_raid_instance(name)
                self.assertIsNotNone(context)
                assert context is not None
                self.assertEqual(context.zone, "The Plane of Fear")
                self.assertEqual(context.mode, mode)
                self.assertEqual(context.difficulty, 0)
                self.assertEqual(context.label, "Normal")

        # The open-world zone has no instance suffix and is not D0.
        self.assertIsNone(parse_raid_instance("The Plane of Fear"))

    def test_environmental_prose_does_not_clear_active_context(self):
        tracker = RaidContextTracker()
        context = tracker.observe_zone(
            "The Plane of Fear - Group 1 (Awakened)")
        self.assertIsNotNone(context)
        retained = tracker.observe_zone(
            "an area where levitation effects do not function")
        self.assertIs(retained, context)
        self.assertIs(tracker.active, context)

    def test_plain_real_zone_entry_clears_previous_instance(self):
        tracker = RaidContextTracker()
        tracker.observe_zone("Nagafen's Lair - Solo 4 (Refined)")
        self.assertIsNotNone(tracker.active)
        tracker.observe_zone("The Nexus")
        self.assertIsNone(tracker.active)
        self.assertIsNone(tracker.snapshot())


if __name__ == "__main__":
    unittest.main()
