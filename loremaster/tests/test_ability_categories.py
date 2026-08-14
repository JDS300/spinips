import importlib.util
import sys
import unittest
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))
SPEC = importlib.util.spec_from_file_location(
    "loremaster_ability_category_test_app", LOREMASTER_DIR / "loremaster.py")
LOREMASTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LOREMASTER
SPEC.loader.exec_module(LOREMASTER)


class AbilityCategoryTests(unittest.TestCase):
    def test_parser_marks_direct_spells_and_uncast_nonmelee_as_procs(self):
        stats = LOREMASTER.SessionStats("Spin")
        lines = (
            "[Thu Aug 13 18:00:00 2026] You begin casting Smite.",
            "[Thu Aug 13 18:00:02 2026] You hit a rock golem for 125 points of magic damage by Smite.",
            "[Thu Aug 13 18:00:03 2026] You hit a rock golem for 75 points of magic damage by Ykesha.",
            "[Thu Aug 13 18:00:04 2026] a rock golem has taken 20 damage from your Ignite Blood.",
            "[Thu Aug 13 18:00:05 2026] You slash a rock golem for 40 points of damage.",
        )
        for line in lines:
            parsed = LOREMASTER.parse_line(line)
            self.assertIsNotNone(parsed)
            stats.apply(*parsed)

        self.assertIsNotNone(stats.fight)
        categories = stats.fight.source_categories
        self.assertEqual(categories["Spell: Smite"], "spell")
        self.assertEqual(categories["Proc: Ykesha"], "proc")
        self.assertEqual(categories["DoT: Ignite Blood"], "dot")
        self.assertEqual(categories["Melee"], "melee")

        snapshot = stats.snapshot(parsed[0])
        self.assertEqual(snapshot["fight_sources"]["Spell: Smite"]["category"],
                         "spell")
        self.assertEqual(snapshot["fight_sources"]["Proc: Ykesha"]["category"],
                         "proc")

    def test_one_direct_cast_keeps_every_aoe_result_typed_as_spell(self):
        stats = LOREMASTER.SessionStats("Spin")
        lines = (
            "[Thu Aug 13 18:00:00 2026] You begin casting Column of Lightning.",
            "[Thu Aug 13 18:00:02 2026] You hit mob one for 100 points of magic damage by Column of Lightning.",
            "[Thu Aug 13 18:00:02 2026] You hit mob two for 90 points of magic damage by Column of Lightning.",
            "[Thu Aug 13 18:00:03 2026] You hit mob three for 80 points of magic damage by Column of Lightning.",
        )
        for line in lines:
            stats.apply(*LOREMASTER.parse_line(line))

        self.assertEqual(
            stats.fight.source_categories["Spell: Column of Lightning"],
            "spell")
        self.assertNotIn("Proc: Column of Lightning", stats.fight.sources)
        self.assertEqual(
            stats.fight.sources["Spell: Column of Lightning"]["t"], 270)

    def test_plain_nonmelee_requires_recent_cast_evidence(self):
        unproven = LOREMASTER.SessionStats("Spin")
        unproven.apply(*LOREMASTER.parse_line(
            "[Thu Aug 13 18:00:00 2026] You hit a golem for 40 points of non-melee damage."))
        snapshot = unproven.snapshot(unproven.last_event)
        self.assertEqual(
            snapshot["fight_sources"]["Unattributed non-melee"]["category"],
            "unknown")

        proven = LOREMASTER.SessionStats("Spin")
        for line in (
            "[Thu Aug 13 18:00:00 2026] You begin casting Shock of Lightning.",
            "[Thu Aug 13 18:00:02 2026] You hit a golem for 40 points of non-melee damage.",
        ):
            proven.apply(*LOREMASTER.parse_line(line))
        self.assertEqual(
            proven.fight.source_categories["Spell: Shock of Lightning"],
            "spell")


if __name__ == "__main__":
    unittest.main()
