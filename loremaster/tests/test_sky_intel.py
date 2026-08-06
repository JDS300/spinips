import sys
import tempfile
import unittest
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from sky_intel import (  # noqa: E402
    inventory_names_from_text,
    load_bundled_catalog,
    normalize_item_name,
    map_marker_line,
    write_map_marker,
)


class PlaneOfSkyIntelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_bundled_catalog(LOREMASTER_DIR)

    def test_bundled_snapshot_is_complete_and_offline(self):
        self.assertGreaterEqual(len(self.catalog.rows), 200)
        self.assertGreaterEqual(len(self.catalog.search_rewards()), 90)
        self.assertEqual(self.catalog.metadata["runtime_network_required"], False)

    def test_inventory_parser_uses_name_header_and_old_second_column(self):
        modern = "Location\tName\tID\nGeneral1\tWind Tablet\t123\nGeneral2\tEmpty\t0\n"
        legacy = "General1\tWind Tablet\t123\n"
        self.assertEqual(inventory_names_from_text(modern), ["Wind Tablet"])
        self.assertEqual(inventory_names_from_text(legacy), ["Wind Tablet"])

    def test_item_normalization_matches_augments_and_rank_suffixes(self):
        self.assertEqual(normalize_item_name("  Wind   Tablet +3 "), "wind tablet")
        self.assertEqual(normalize_item_name("Wind Tablet (Lore)"), "wind tablet")

    def test_looted_turn_in_finds_rewards_and_builds_target_plan(self):
        row = self.catalog.rows[0]
        matches = self.catalog.item_matches(row.quest_item)
        self.assertTrue(matches)
        key = (matches[0].class_name, matches[0].npc, matches[0].reward)
        plan = self.catalog.plan(key, [row.quest_item])
        self.assertEqual(plan.reward, row.reward)
        self.assertGreaterEqual(len(plan.owned), 1)
        self.assertEqual(len(plan.required), len(plan.owned) + len(plan.missing))

    def test_map_marker_uses_documented_island_label_and_preserves_user_lines(self):
        marker = map_marker_line("Example Reward", "Isle 3: Gorgalosk")
        self.assertIn("Loremaster_Target_Example_Reward_Isle_3", marker)
        with tempfile.TemporaryDirectory() as tmp:
            layer = Path(tmp) / "airplane_3.txt"
            layer.write_text("P 1, 2, 3, 255, 0, 0, 2, User_Label\n",
                             encoding="utf-8")
            write_map_marker(tmp, "First Reward", "Isle 3: Gorgalosk")
            write_map_marker(tmp, "Second Reward", "Isle 5: The Spiroc Lord")
            text = layer.read_text(encoding="utf-8")
            self.assertIn("User_Label", text)
            self.assertNotIn("First_Reward", text)
            self.assertIn("Second_Reward", text)


if __name__ == "__main__":
    unittest.main()
