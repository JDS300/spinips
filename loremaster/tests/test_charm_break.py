import importlib.util
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from charm_break import CharmBreakDetector  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "loremaster_charm_break_test_app", LOREMASTER_DIR / "loremaster.py")
LOREMASTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LOREMASTER
SPEC.loader.exec_module(LOREMASTER)

BASE = datetime(2026, 8, 2, 12, 0, 0)


def log_line(offset: int, message: str) -> str:
    stamp = BASE + timedelta(seconds=offset)
    return f"[{stamp.strftime('%a %b %d %H:%M:%S %Y')}] {message}"


def apply_line(stats, offset: int, message: str):
    parsed = LOREMASTER.parse_line(log_line(offset, message))
    if parsed is None:
        raise AssertionError(f"unparsed test line: {message}")
    return stats.apply(*parsed)


class CharmBreakDetectorTests(unittest.TestCase):
    def test_matching_charm_fade_emits_once_and_clears_claim(self):
        detector = CharmBreakDetector()
        detector.claim("A rock golem", BASE, "Cajoling Whispers VI")

        event = detector.observe_fade(
            spell_name="Cajoling Whispers", occurred_at=BASE + timedelta(seconds=20),
            target_name="a rock golem", is_charm_spell=True)

        self.assertIsNotNone(event)
        self.assertEqual(event.event_id, 1)
        self.assertEqual(event.pet_name, "A rock golem")
        self.assertEqual(event.charm_spell, "Cajoling Whispers")
        self.assertIsNone(detector.active)
        duplicate = detector.observe_fade(
            spell_name="Cajoling Whispers", occurred_at=BASE + timedelta(seconds=21),
            target_name="a rock golem", is_charm_spell=True)
        self.assertIsNone(duplicate)

    def test_unrelated_or_wrong_target_fade_is_not_a_break(self):
        detector = CharmBreakDetector()
        detector.claim("a rat", BASE, "Charm")

        self.assertIsNone(detector.observe_fade(
            spell_name="Mesmerization", occurred_at=BASE + timedelta(seconds=1),
            target_name="a rat", is_charm_spell=False))
        self.assertIsNone(detector.observe_fade(
            spell_name="Charm", occurred_at=BASE + timedelta(seconds=2),
            target_name="a goblin", is_charm_spell=True))
        self.assertEqual(detector.active.pet_name, "a rat")

    def test_targetless_fade_is_proof_with_one_active_charm(self):
        detector = CharmBreakDetector()
        detector.claim("an orc pawn", BASE)
        event = detector.observe_fade(
            spell_name="Charm", occurred_at=BASE + timedelta(seconds=5),
            is_charm_spell=True)
        self.assertEqual(event.pet_name, "an orc pawn")

    def test_death_zone_reset_and_replacement_transitions_are_silent(self):
        detector = CharmBreakDetector()
        detector.claim("a rat", BASE)
        old = detector.clear_silently("a rat")  # death/zone/reset cleanup
        self.assertEqual(old.pet_name, "a rat")
        self.assertIsNone(detector.active)

        detector.claim("a rat", BASE + timedelta(seconds=1))
        detector.claim("a goblin", BASE + timedelta(seconds=2), "Beguile")
        self.assertEqual(detector.active.pet_name, "a goblin")
        # A late fade for the intentionally replaced pet cannot fire.
        self.assertIsNone(detector.observe_fade(
            spell_name="Charm", occurred_at=BASE + timedelta(seconds=3),
            target_name="a rat", is_charm_spell=True))

    def test_repeated_owner_chatter_does_not_create_a_new_claim_episode(self):
        detector = CharmBreakDetector()
        detector.claim("A rock golem", BASE, "Charm")
        detector.claim("a rock golem", BASE + timedelta(seconds=10))
        self.assertEqual(detector.active.claimed_at, BASE)
        self.assertEqual(detector.active.charm_spell, "Charm")


class SessionCharmBreakIntegrationTests(unittest.TestCase):
    def test_apply_returns_one_event_for_the_proven_break_line(self):
        stats = LOREMASTER.SessionStats("Spin")
        self.assertEqual(apply_line(
            stats, 0, "You begin casting Cajoling Whispers VI."), ())
        self.assertEqual(apply_line(
            stats, 1, "a rock golem has been charmed."), ())

        events = apply_line(
            stats, 10,
            "Your Cajoling Whispers spell has worn off of a rock golem.")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].pet_name, "A rock golem")
        self.assertEqual(events[0].occurred_at, BASE + timedelta(seconds=10))
        self.assertFalse(stats.is_charmed_pet("a rock golem"))

        self.assertEqual(apply_line(
            stats, 11,
            "Your Cajoling Whispers spell has worn off of a rock golem."), ())

    def test_wrong_target_does_not_emit_or_release_active_pet(self):
        stats = LOREMASTER.SessionStats("Spin")
        apply_line(stats, 0, "You begin casting Charm.")
        apply_line(stats, 1, "a rat has been charmed.")

        events = apply_line(
            stats, 2, "Your Charm spell has worn off of a goblin.")
        self.assertEqual(events, ())
        self.assertTrue(stats.is_charmed_pet("a rat"))

    def test_targetless_fade_emits_for_the_active_pet(self):
        stats = LOREMASTER.SessionStats("Spin")
        apply_line(stats, 0, "You begin casting Beguile.")
        apply_line(stats, 1, "an orc pawn has been charmed.")
        events = apply_line(stats, 3, "Your Beguile spell has worn off.")
        self.assertEqual([event.pet_name for event in events], ["An orc pawn"])
        self.assertFalse(stats.is_charmed_pet("an orc pawn"))

    def test_pet_death_character_death_zone_and_replacement_do_not_emit(self):
        pet_death = LOREMASTER.SessionStats("Spin")
        apply_line(pet_death, 0, "You begin casting Charm.")
        apply_line(pet_death, 1, "a rat has been charmed.")
        self.assertEqual(apply_line(
            pet_death, 2, "A rat has been slain by a goblin!"), ())

        player_death = LOREMASTER.SessionStats("Spin")
        apply_line(player_death, 0, "You begin casting Charm.")
        apply_line(player_death, 1, "a rat has been charmed.")
        self.assertEqual(apply_line(
            player_death, 2, "You have been slain by a goblin!"), ())

        zoning = LOREMASTER.SessionStats("Spin")
        apply_line(zoning, 0, "You begin casting Charm.")
        apply_line(zoning, 1, "a rat has been charmed.")
        self.assertEqual(apply_line(
            zoning, 2, "You have entered Blackburrow."), ())

        replaced = LOREMASTER.SessionStats("Spin")
        apply_line(replaced, 0, "You begin casting Charm.")
        apply_line(replaced, 1, "a rat has been charmed.")
        apply_line(replaced, 2, "You begin casting Beguile.")
        self.assertEqual(apply_line(
            replaced, 3, "a goblin has been charmed."), ())
        self.assertFalse(replaced.is_charmed_pet("a rat"))
        self.assertTrue(replaced.is_charmed_pet("a goblin"))


if __name__ == "__main__":
    unittest.main()
