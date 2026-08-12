import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

from desktop_worker import HeadlessEngine  # noqa: E402


class DesktopWorkerTests(unittest.TestCase):
    def test_log_attach_recovers_zone_and_composition_beyond_combat_warm_start(self):
        with tempfile.TemporaryDirectory() as root:
            log = Path(root) / "eqlog_Spin_qeynos.txt"
            log.write_text(
                "[Sat Aug 08 10:00:00 2026] You have entered The Plane of Fear.\n"
                "[Sat Aug 08 10:00:01 2026] Your active classes are PAL / MNK / ENC.\n"
                "[Sat Aug 08 10:00:02 2026] AromeK has joined the group.\n"
                "[Sat Aug 08 17:00:00 2026] Auto attack is off.\n",
                encoding="latin-1")
            engine = HeadlessEngine(log_path=str(log), data_dir=root)
            try:
                _parsed, switched = engine.poll()
                event = engine.snapshot_event(datetime(2026, 8, 8, 17, 0, 1))
            finally:
                engine.close()
            self.assertTrue(switched)
            self.assertEqual(event["snapshot"]["character"]["zone"],
                             "The Plane of Fear")
            self.assertEqual(event["snapshot"]["character"]["composition"],
                             "PAL / MNK / ENC")
            self.assertEqual(event["snapshot"]["groupMembers"], ("AromeK",))

    def test_explicit_group_members_are_distinct_from_nearby_actors(self):
        with tempfile.TemporaryDirectory() as root:
            engine = HeadlessEngine(data_dir=root)
            try:
                engine.stats.character = "Spin"
                for line in (
                    "[Sat Aug 08 17:00:00 2026] AromeK has joined the group.",
                    "[Sat Aug 08 17:00:01 2026] You slash a rock golem for 100 points of damage.",
                    "[Sat Aug 08 17:00:02 2026] AromeK slashes a rock golem for 70 points of damage.",
                    "[Sat Aug 08 17:00:03 2026] Stranger slashes a rock golem for 40 points of damage.",
                ):
                    self.assertTrue(engine.process_line(line))
                event = engine.snapshot_event(datetime(2026, 8, 8, 17, 0, 4))
            finally:
                engine.close()
            actors = {row["name"]: row for row in
                      event["snapshot"]["encounters"][-1]["actors"]}
            self.assertEqual(actors["AromeK"]["role"], "group")
            self.assertEqual(actors["Stranger"]["role"], "observed")
            self.assertEqual(event["snapshot"]["groupMembers"], ("AromeK",))
            self.assertEqual(event["snapshot"]["combat"]["fightDamage"], 100)

    def test_manual_composition_setting_is_validated_and_applied(self):
        with tempfile.TemporaryDirectory() as root:
            engine = HeadlessEngine(data_dir=root)
            try:
                self.assertTrue(engine.set_composition("pal/mnk/enc"))
                self.assertFalse(engine.set_composition("pal/enc"))
                event = engine.snapshot_event(datetime(2026, 8, 8, 17, 0, 0))
            finally:
                engine.close()
            self.assertEqual(event["snapshot"]["character"]["composition"],
                             "PAL / MNK / ENC")

    def test_auto_attack_state_crosses_desktop_boundary_exactly(self):
        with tempfile.TemporaryDirectory() as root:
            engine = HeadlessEngine(data_dir=root)
            try:
                self.assertTrue(engine.process_line(
                    "[Fri Aug 07 19:59:58 2026] Auto attack is on."))
                enabled = engine.snapshot_event(
                    datetime(2026, 8, 7, 19, 59, 59))
                self.assertTrue(engine.process_line(
                    "[Fri Aug 07 20:00:00 2026] Auto attack is off."))
                disabled = engine.snapshot_event(
                    datetime(2026, 8, 7, 20, 0, 1))
            finally:
                engine.close()
            self.assertTrue(enabled["snapshot"]["combat"]["autoAttack"])
            self.assertFalse(disabled["snapshot"]["combat"]["autoAttack"])

    def test_live_snapshot_preserves_damage_and_control_parity(self):
        with tempfile.TemporaryDirectory() as root:
            engine = HeadlessEngine(data_dir=root)
            try:
                self.assertTrue(engine.set_raid_difficulty(2))
                lines = [
                    "[Fri Aug 07 20:00:00 2026] You begin casting Mesmerize.",
                    "[Fri Aug 07 20:00:02 2026] a soul carrier has been mesmerized.",
                    "[Fri Aug 07 20:00:03 2026] You slash Lord Nagafen for 100 points of damage.",
                    "[Fri Aug 07 20:00:04 2026] You have slain Lord Nagafen!",
                ]
                for line in lines:
                    self.assertTrue(engine.process_line(line))
                event = engine.snapshot_event(datetime(2026, 8, 7, 20, 0, 5))
            finally:
                engine.close()
            self.assertEqual(event["eventType"], "engine.snapshot")
            self.assertEqual(event["snapshot"]["combat"]["personalDamage"], 100)
            self.assertEqual(event["snapshot"]["controls"][0]["kind"], "mez")
            weekly = event["snapshot"]["weekly"]
            self.assertEqual(weekly["completedCount"], 1)
            self.assertNotIn("altZLockouts", weekly)
            self.assertNotIn("altZScan", weekly)
            nagafen = next(row for row in weekly["raids"]
                           if row["target"] == "Lord Nagafen")
            self.assertTrue(nagafen["difficulties"][2])

    def test_selected_missing_directory_reports_searching(self):
        with tempfile.TemporaryDirectory() as root:
            engine = HeadlessEngine(log_path=str(Path(root) / "missing"), data_dir=root)
            try:
                health = engine.health()
            finally:
                engine.close()
            self.assertEqual(health["state"], "searching")
            self.assertIn("selected location", health["detail"])

    def test_proven_charm_break_crosses_desktop_boundary_once(self):
        with tempfile.TemporaryDirectory() as root:
            engine = HeadlessEngine(data_dir=root)
            try:
                for line in (
                    "[Fri Aug 07 20:00:00 2026] You begin casting Charm.",
                    "[Fri Aug 07 20:00:01 2026] a rock golem has been charmed.",
                    "[Fri Aug 07 20:00:03 2026] Your Charm spell has worn off of a rock golem.",
                ):
                    engine.process_line(line)
                first = engine.snapshot_event(datetime(2026, 8, 7, 20, 0, 4))
                second = engine.snapshot_event(datetime(2026, 8, 7, 20, 0, 9))
            finally:
                engine.close()
            self.assertEqual(first["snapshot"]["alerts"][0]["kind"], "charmBreak")
            self.assertEqual(first["snapshot"]["alerts"][0]["target"], "A rock golem")
            self.assertEqual(second["snapshot"]["alerts"], [])

    def test_alert_preferences_control_general_log_alerts(self):
        with tempfile.TemporaryDirectory() as root:
            engine = HeadlessEngine(data_dir=root)
            try:
                engine.stats.character = "Spin"
                engine.set_alert_config({
                    "alertsEnabled": True, "alertTells": True,
                    "alertSeconds": 7})
                engine.process_line(
                    "[Fri Aug 07 20:00:00 2026] Friend tells you, 'Ready?'")
                event = engine.snapshot_event(datetime(2026, 8, 7, 20, 0, 1))
                engine.alerts.clear()
                engine.set_alert_config({"alertsEnabled": False})
                engine.process_line(
                    "[Fri Aug 07 20:00:02 2026] Friend tells you, 'Again?'")
                muted = engine.snapshot_event(datetime(2026, 8, 7, 20, 0, 3))
            finally:
                engine.close()
            self.assertEqual(event["snapshot"]["alerts"][0]["kind"], "tell_in")
            self.assertEqual(event["snapshot"]["alerts"][0]["severity"], "info")
            self.assertEqual(muted["snapshot"]["alerts"], [])

    def test_nearby_players_boss_kill_does_not_credit_weekly_ledger(self):
        with tempfile.TemporaryDirectory() as root:
            engine = HeadlessEngine(data_dir=root)
            try:
                engine.process_line(
                    "[Fri Aug 07 20:00:00 2026] Lord Nagafen has been slain by Stranger!")
                event = engine.snapshot_event(datetime(2026, 8, 7, 20, 0, 1))
            finally:
                engine.close()
            self.assertEqual(event["snapshot"]["weekly"]["completedCount"], 0)

    def test_group_killing_blow_prompts_when_self_engaged_the_raid_boss(self):
        with tempfile.TemporaryDirectory() as root:
            engine = HeadlessEngine(data_dir=root)
            try:
                engine.process_line(
                    "[Fri Aug 07 20:00:00 2026] You slash Cazic-Thule for 100 points of damage.")
                engine.process_line(
                    "[Fri Aug 07 20:00:01 2026] Cazic-Thule has been slain by AromeK!")
                event = engine.snapshot_event(datetime(2026, 8, 7, 20, 0, 2))
            finally:
                engine.close()
            weekly = event["snapshot"]["weekly"]
            self.assertEqual(weekly["pendingRaidTarget"], "Cazic-Thule")
            self.assertEqual(weekly["completedCount"], 0)

    def test_boss_kill_waits_for_explicit_difficulty(self):
        with tempfile.TemporaryDirectory() as root:
            engine = HeadlessEngine(data_dir=root)
            try:
                engine.process_line(
                    "[Fri Aug 07 20:00:00 2026] You have slain Lady Vox!")
                pending = engine.snapshot_event(datetime(2026, 8, 7, 20, 0, 1))
                self.assertEqual(
                    pending["snapshot"]["weekly"]["pendingRaidTarget"], "Lady Vox")
                self.assertEqual(
                    pending["snapshot"]["weekly"]["completedCount"], 0)
                self.assertTrue(engine.set_raid_difficulty(4))
                credited = engine.snapshot_event(datetime(2026, 8, 7, 20, 0, 2))
            finally:
                engine.close()
            self.assertEqual(credited["snapshot"]["weekly"]["completedCount"], 1)


if __name__ == "__main__":
    unittest.main()
