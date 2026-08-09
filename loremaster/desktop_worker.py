#!/usr/bin/env python3
"""Headless Loremaster engine for the Electron desktop application.

stdin accepts one JSON object per line. stdout emits JSON events only; human
diagnostics go to stderr.  This intentionally small boundary lets Electron own
windows, settings and animation while the proven parser remains authoritative.
"""

from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import queue
import sys
import threading
import time
from datetime import datetime, timedelta

from control_snapshot import merge_control_snapshots
from engine_protocol import build_engine_snapshot, snapshot_event
try:
    # Script/PyInstaller import used by the production worker.
    from loremaster import (LogWatcher, SessionStats, apply_log_models,
                            check_alerts, normalize_composition, parse_line)
except (ImportError, AttributeError):
    # ``python -m unittest loremaster.tests...`` reserves ``loremaster`` as a
    # namespace package. Load the runtime file under a private name so worker
    # tests exercise the exact same implementation without import ambiguity.
    runtime_path = Path(__file__).resolve().with_name("loremaster.py")
    runtime_spec = importlib.util.spec_from_file_location(
        "_loremaster_runtime", runtime_path)
    if runtime_spec is None or runtime_spec.loader is None:
        raise ImportError(f"Could not load Loremaster runtime at {runtime_path}")
    runtime_module = importlib.util.module_from_spec(runtime_spec)
    sys.modules[runtime_spec.name] = runtime_module
    runtime_spec.loader.exec_module(runtime_module)
    LogWatcher = runtime_module.LogWatcher
    SessionStats = runtime_module.SessionStats
    apply_log_models = runtime_module.apply_log_models
    check_alerts = runtime_module.check_alerts
    parse_line = runtime_module.parse_line
    normalize_composition = runtime_module.normalize_composition
from lull_timer import LullTracker
from mez_timer import MezTracker
from hover_ocr import HoverOcrService
from instance_lockout_ocr import (
    ParsedRaidLockout, parse_instance_character, parse_instance_lockouts)
from weekly_tracker import DIFFICULTIES, WeeklyBossTracker


SNAPSHOT_INTERVAL_SECONDS = 0.25
POLL_INTERVAL_SECONDS = 0.08

# JSONL is an explicit UTF-8 protocol even on Windows systems whose console
# code page is still cp1252. Electron decodes the worker stream as UTF-8.
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="strict")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="strict")


class HeadlessEngine:
    """One deterministic parser session with replaceable log input."""

    def __init__(self, *, log_path: str = "", data_dir: str | Path | None = None,
                 now: datetime | None = None) -> None:
        self.data_dir = Path(data_dir or os.environ.get(
            "LOREMASTER_APP_DATA_DIR", Path.cwd()))
        self.weekly = WeeklyBossTracker(
            storage_path=self.data_dir / "weekly_boss_kills.json")
        self.instance_lockout_path = self.data_dir / "alt_z_lockouts.json"
        self.instance_lockouts: list[dict] = []
        self.lockout_scan = {
            "status": "idle",
            "detail": "Open Alt+Z, point at Outstanding Instance Timers, then press Ctrl+Shift+Z.",
            "scannedAt": "",
            "importedCount": 0,
            "hotkey": "Ctrl+Shift+Z",
        }
        self._lockout_request_id = 0
        self.lockout_ocr = HoverOcrService()
        self._load_instance_lockouts()
        self.raid_difficulty: int | None = None
        self.configured_composition = ""
        self.pending_raid_target = ""
        self.pending_raid_seconds = 0.0
        self.sequence = 0
        self.stats = SessionStats()
        self.mez = MezTracker()
        self.lull = LullTracker()
        self.alerts: list[dict] = []
        self.alert_config = {
            "alerts_enabled": True,
            "alert_sound": True,
            "alert_seconds": 5,
            "alert_charm_break": True,
            "alert_tells": True,
            "alert_summon": True,
            "alert_death": True,
            "alert_big_hit": True,
            "alert_name_called": True,
            "big_hit_threshold": 800,
            "mez_timers_enabled": True,
            "mez_warning_seconds": 10,
            "lull_timers_enabled": True,
            "lull_warning_seconds": 12,
            "custom_alerts": [],
        }
        self.watcher: LogWatcher
        self.configured_path = ""
        self.set_log_path(log_path)
        self.last_observed_at = now or datetime.now()

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.astimezone()

    @staticmethod
    def _parse_stamp(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.astimezone()
        except (TypeError, ValueError):
            return None

    def _load_instance_lockouts(self) -> None:
        try:
            payload = json.loads(self.instance_lockout_path.read_text(encoding="utf-8"))
            rows = payload.get("lockouts", []) if isinstance(payload, dict) else []
            self.instance_lockouts = [row for row in rows if (
                isinstance(row, dict)
                and isinstance(row.get("target"), str)
                and row.get("difficulty") in DIFFICULTIES
                and self._parse_stamp(str(row.get("expiresAt", ""))) is not None
            )]
            scan = payload.get("lastScan", {}) if isinstance(payload, dict) else {}
            if isinstance(scan, dict) and isinstance(scan.get("scannedAt"), str):
                self.lockout_scan.update({
                    "status": "success" if self.instance_lockouts else "idle",
                    "detail": str(scan.get("detail") or self.lockout_scan["detail"])[:240],
                    "scannedAt": scan.get("scannedAt", ""),
                    "importedCount": int(scan.get("importedCount", 0) or 0),
                })
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.instance_lockouts = []

    def _save_instance_lockouts(self) -> None:
        self.instance_lockout_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.instance_lockout_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({
            "schemaVersion": 1,
            "lockouts": self.instance_lockouts,
            "lastScan": self.lockout_scan,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, self.instance_lockout_path)

    def request_instance_lockout_scan(self) -> None:
        self.lockout_scan.update({
            "status": "scanning",
            "detail": "Reading the visible Alt+Z Outstanding Instance Timers…",
            "importedCount": 0,
        })
        self._lockout_request_id = self.lockout_ocr.submit()

    def import_instance_lockouts(self, rows: list[ParsedRaidLockout], *,
                                 scanned_at: datetime | None = None,
                                 character_hint: str = "") -> int:
        observed_at = self._aware(scanned_at or datetime.now())
        character = (character_hint or self.stats.character or "?").strip() or "?"
        by_key = {
            (str(row.get("character", "?")).casefold(),
             str(row.get("target", "")).casefold(), row.get("difficulty")): row
            for row in self.instance_lockouts
        }
        for lockout in rows:
            if character != "?":
                by_key.pop(("?", lockout.target.casefold(), lockout.difficulty), None)
                by_key.pop(("", lockout.target.casefold(), lockout.difficulty), None)
            expires_at = observed_at + timedelta(seconds=lockout.remaining_seconds)
            stored = {
                "target": lockout.target,
                "difficulty": lockout.difficulty,
                "instanceName": lockout.instance_name,
                "eventName": lockout.event_name,
                "character": character,
                "scannedAt": observed_at.isoformat(timespec="seconds"),
                "expiresAt": expires_at.isoformat(timespec="seconds"),
            }
            by_key[(character.casefold(), lockout.target.casefold(),
                    lockout.difficulty)] = stored
            self.weekly.set_completion(
                observed_at, lockout.target, lockout.difficulty,
                character=character, completed=True)
        self.instance_lockouts = list(by_key.values())
        stamp = observed_at.isoformat(timespec="seconds")
        count = len(rows)
        self.lockout_scan.update({
            "status": "success",
            "detail": (f"Imported {count} visible raid lockout"
                       f"{'s' if count != 1 else ''}. Scroll Alt+Z and scan again to merge more rows."),
            "scannedAt": stamp,
            "importedCount": count,
        })
        self._save_instance_lockouts()
        if self.alert_config.get("alerts_enabled", True):
            self.alerts.append({
                "id": f"lockoutSync-{observed_at.timestamp():.3f}",
                "kind": "lockoutSync",
                "severity": "info",
                "title": "LOCKOUTS SYNCED",
                "target": f"{count} visible D0–D4 raid lockout{'s' if count != 1 else ''}",
                "occurredAt": stamp,
                "expiresAt": (observed_at + timedelta(
                    seconds=self.alert_config["alert_seconds"])).isoformat(
                        timespec="milliseconds"),
            })
        return count

    def _poll_instance_lockout_scan(self) -> None:
        for result in self.lockout_ocr.poll():
            if result.request_id != self._lockout_request_id:
                continue
            if result.error:
                self.lockout_scan.update({
                    "status": "error",
                    "detail": result.error,
                    "importedCount": 0,
                })
                continue
            rows = parse_instance_lockouts(result.lines)
            if not rows:
                self.lockout_scan.update({
                    "status": "error",
                    "detail": ("No D0–D4 raid rows were recognized. Keep EverQuest focused, "
                               "point inside the timer table, and scan the visible rows again."),
                    "importedCount": 0,
                })
                continue
            self.import_instance_lockouts(
                rows, character_hint=parse_instance_character(result.lines))

    def _instance_lockout_snapshot(self, now: datetime) -> list[dict]:
        observed_at = self._aware(now)
        character = (self.stats.character or "?").strip().casefold()
        visible = []
        for row in self.instance_lockouts:
            expires_at = self._parse_stamp(str(row.get("expiresAt", "")))
            if expires_at is None:
                continue
            remaining = max(0, int((expires_at - observed_at).total_seconds()))
            row_character = str(row.get("character", "?")).strip().casefold()
            if remaining <= 0 or (
                    character not in ("", "?")
                    and row_character not in ("", "?", character)):
                continue
            visible.append({
                "target": row.get("target", ""),
                "difficulty": row.get("difficulty", 0),
                "remainingSeconds": remaining,
                "instanceName": row.get("instanceName", ""),
                "eventName": row.get("eventName", ""),
                "expiresAt": row.get("expiresAt", ""),
            })
        return sorted(visible, key=lambda row: (
            int(row["remainingSeconds"]), str(row["target"])))

    def set_log_path(self, value: str) -> None:
        old = getattr(self, "watcher", None)
        if old is not None:
            old.close()
        cleaned = str(value or "").strip()
        candidate = Path(cleaned) if cleaned else None
        explicit = str(candidate) if candidate and candidate.suffix.casefold() == ".txt" else None
        directory = str(candidate) if candidate and explicit is None else None
        self.watcher = LogWatcher(directory, explicit)
        self.configured_path = cleaned

    def reset(self) -> None:
        character = self.stats.character
        composition = self.stats.composition
        self.stats = SessionStats(character, composition=composition)
        self.mez.clear()
        self.lull.clear()
        self.alerts.clear()

    def set_alert_config(self, value) -> None:
        if not isinstance(value, dict):
            return
        mapping = {
            "alertsEnabled": "alerts_enabled",
            "alertSound": "alert_sound",
            "alertSeconds": "alert_seconds",
            "alertCharmBreak": "alert_charm_break",
            "alertTells": "alert_tells",
            "alertSummon": "alert_summon",
            "alertDeath": "alert_death",
            "alertBigHit": "alert_big_hit",
            "alertNameCalled": "alert_name_called",
            "bigHitThreshold": "big_hit_threshold",
            "mezTimersEnabled": "mez_timers_enabled",
            "mezWarningSeconds": "mez_warning_seconds",
            "lullTimersEnabled": "lull_timers_enabled",
            "lullWarningSeconds": "lull_warning_seconds",
        }
        for source, target in mapping.items():
            if source in value:
                self.alert_config[target] = value[source]
        for key, low, high in (
                ("alert_seconds", 1, 15),
                ("big_hit_threshold", 1, 999999),
                ("mez_warning_seconds", 3, 30),
                ("lull_warning_seconds", 3, 30)):
            try:
                self.alert_config[key] = max(
                    low, min(high, int(self.alert_config[key])))
            except (TypeError, ValueError):
                pass

    def set_raid_difficulty(self, value: int | None) -> bool:
        if value is not None and value not in DIFFICULTIES:
            return False
        self.raid_difficulty = value
        if value is not None and self.pending_raid_target:
            self.weekly.observe_kill(
                self.last_observed_at, self.pending_raid_target,
                zone=self.stats.zone, character=self.stats.character,
                difficulty=value, duration_seconds=self.pending_raid_seconds)
            self.pending_raid_target = ""
            self.pending_raid_seconds = 0.0
        return True

    def set_composition(self, value: str) -> bool:
        cleaned = str(value or "").strip()
        if not cleaned:
            self.configured_composition = ""
            if self.stats.composition_source == "desktop setting":
                self.stats.composition = ""
                self.stats.composition_source = "unset"
            return True
        try:
            canonical = normalize_composition(cleaned)
        except ValueError:
            return False
        self.configured_composition = canonical
        self.stats.set_composition(canonical, source="desktop setting")
        return True

    def set_raid_completion(self, target: str, difficulty: int,
                            completed: bool) -> bool:
        return self.weekly.set_completion(
            self.last_observed_at, target, difficulty,
            character=self.stats.character, completed=completed)

    def _switch_character(self) -> None:
        context = self.watcher.recent_context()
        composition = str(self.configured_composition
                          or context.get("composition", ""))
        self.stats = SessionStats(
            self.watcher.character or "?", composition=composition)
        self.stats.zone = str(context.get("zone", ""))
        self.stats.group_members = set(context.get("group_members", ()))
        if self.stats.zone:
            self.stats.zones.append(self.stats.zone)
        self.mez.clear()
        self.lull.clear()

    def process_line(self, line: str) -> bool:
        parsed = parse_line(line)
        if parsed is None:
            return False
        occurred_at, kind, groups = parsed
        self.last_observed_at = occurred_at
        charm_breaks = apply_log_models(
            self.stats, self.mez, occurred_at, kind, groups,
            lull_tracker=self.lull, caster_level=self.stats.level)
        raw_message = line.split("] ", 1)[1] if "] " in line else line
        triggered = check_alerts(
            kind, groups, raw_message, self.stats.character,
            self.alert_config, charm_breaks)
        for offset, (severity, message) in enumerate(triggered):
            alert_kind = "charmBreak" if message.startswith("CHARM BROKE") else kind
            title, _, target = message.partition(" — ")
            if alert_kind == "charmBreak" and charm_breaks:
                target = charm_breaks[0].pet_name
            event_key = getattr(charm_breaks[0], "event_id", "") if charm_breaks else ""
            alert_id = (f"{alert_kind}-{event_key}" if event_key else
                        f"{alert_kind}-{occurred_at.timestamp():.3f}-{offset}")
            self.alerts.append({
                "id": alert_id,
                "kind": alert_kind,
                "severity": severity,
                "title": title,
                "target": target,
                "occurredAt": occurred_at.isoformat(timespec="milliseconds"),
                "expiresAt": (occurred_at + timedelta(
                    seconds=self.alert_config["alert_seconds"])).isoformat(
                        timespec="milliseconds"),
            })
        # A raid's killing blow is commonly attributed to a groupmate. Credit
        # it only when ownership is direct (self/pet) or this encounter
        # contains proven self/pet damage against the same tracked boss. That
        # captures real group clears without marking unrelated nearby kills.
        target = groups.get("target", "")
        raid_target = self.weekly.match_target(target)
        engaged_raid_target = bool(
            kind == "kill_other" and raid_target and self.stats.fight and
            any(
                damage > 0 and self.weekly.match_target(fight_target) == raid_target
                for fight_target, damage in self.stats.fight.targets.items()
            )
        )
        weekly_credit = (kind == "kill_you" or (
            kind == "kill_other" and (
                self.stats.is_pet(groups.get("killer", "")) or
                engaged_raid_target)))
        if weekly_credit:
            if raid_target:
                if self.raid_difficulty is None:
                    self.pending_raid_target = raid_target.name
                    self.pending_raid_seconds = (
                        self.stats.fight.seconds if self.stats.fight else 0.0)
                else:
                    self.weekly.observe_kill(
                        occurred_at, raid_target.name, zone=self.stats.zone,
                        character=self.stats.character,
                        difficulty=self.raid_difficulty,
                        duration_seconds=(self.stats.fight.seconds
                                          if self.stats.fight else 0.0))
        return True

    def poll(self) -> tuple[int, bool]:
        self._poll_instance_lockout_scan()
        lines, switched = self.watcher.poll()
        if switched:
            self._switch_character()
        parsed = sum(1 for line in lines if self.process_line(line))
        return parsed, switched

    def health(self) -> dict:
        active = self.watcher.path
        if active is not None:
            state = "live"
            detail = f"Reading {active.name}"
        elif self.configured_path:
            state = "searching"
            detail = "Waiting for an EverQuest log in the selected location"
        else:
            state = "searching"
            detail = "Searching common EverQuest Legends log locations"
        return {
            "state": state,
            "detail": detail,
            "configuredPath": self.configured_path,
            "activeLogPath": str(active) if active else "",
            "character": self.stats.character,
            "server": self.watcher.server,
        }

    def snapshot_event(self, now: datetime | None = None) -> dict:
        observed_at = now or datetime.now()
        stats = self.stats.snapshot(observed_at)
        mez_snapshot = self.mez.snapshot(
            observed_at,
            warning_seconds=self.alert_config["mez_warning_seconds"])
        lull_snapshot = self.lull.snapshot(
            observed_at,
            warning_seconds=self.alert_config["lull_warning_seconds"])
        controls = merge_control_snapshots(
            mez_snapshot, lull_snapshot, limit=6,
            include_mez=bool(self.alert_config.get("mez_timers_enabled", True)),
            include_lull=bool(self.alert_config.get("lull_timers_enabled", True)))
        self.sequence += 1
        snapshot = build_engine_snapshot(
            sequence=self.sequence, observed_at=observed_at,
            stats_snapshot=stats, control_snapshot=controls)
        event = snapshot_event(snapshot).to_dict()
        weekly_character = (self.stats.character or "").strip()
        weekly = self.weekly.snapshot(
            observed_at,
            character="" if weekly_character in ("", "?") else weekly_character)
        weekly["activeDifficulty"] = self.raid_difficulty
        weekly["pendingRaidTarget"] = self.pending_raid_target
        weekly["altZLockouts"] = self._instance_lockout_snapshot(observed_at)
        weekly["altZScan"] = dict(self.lockout_scan)
        event["snapshot"]["weekly"] = weekly
        self.alerts = [alert for alert in self.alerts
                       if self._aware(datetime.fromisoformat(alert["expiresAt"]))
                       > self._aware(observed_at)]
        event["snapshot"]["alerts"] = list(self.alerts)
        return event

    def close(self) -> None:
        self.lockout_ocr.close()
        self.watcher.close()


class JsonLineWorker:
    def __init__(self) -> None:
        self.commands: queue.Queue[dict] = queue.Queue()
        self.stopping = False
        self.engine = HeadlessEngine(
            data_dir=os.environ.get("LOREMASTER_APP_DATA_DIR"))
        self._reader = threading.Thread(
            target=self._read_commands, name="LoremasterDesktopCommands",
            daemon=True)

    @staticmethod
    def emit(payload: dict) -> None:
        sys.stdout.write(json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    def _read_commands(self) -> None:
        for raw in sys.stdin:
            try:
                value = json.loads(raw)
                if isinstance(value, dict):
                    self.commands.put(value)
            except json.JSONDecodeError as exc:
                print(f"invalid desktop command: {exc}", file=sys.stderr)
        self.commands.put({"type": "engine.shutdown"})

    def _handle(self, command: dict) -> None:
        kind = command.get("type")
        if kind == "engine.initialize":
            if not self.engine.set_composition(str(command.get("composition") or "")):
                raise ValueError("composition must contain exactly three valid classes")
            self.engine.set_log_path(str(command.get("logPath") or ""))
            self.engine.set_raid_difficulty(command.get("raidDifficulty"))
            self.engine.set_alert_config(command.get("alertConfig"))
        elif kind == "engine.set-log-path":
            self.engine.set_log_path(str(command.get("logPath") or ""))
        elif kind == "engine.set-raid-difficulty":
            if not self.engine.set_raid_difficulty(command.get("raidDifficulty")):
                raise ValueError("raidDifficulty must be null or an integer from 0 to 4")
        elif kind == "engine.set-alert-config":
            self.engine.set_alert_config(command.get("alertConfig"))
        elif kind == "engine.set-composition":
            if not self.engine.set_composition(str(command.get("composition") or "")):
                raise ValueError("composition must contain exactly three valid classes")
        elif kind == "engine.set-raid-completion":
            self.engine.set_raid_completion(
                str(command.get("target") or ""),
                int(command.get("difficulty", -1)),
                bool(command.get("completed")))
        elif kind == "engine.scan-alt-z-lockouts":
            self.engine.request_instance_lockout_scan()
        elif kind == "engine.reset":
            self.engine.reset()
        elif kind == "engine.shutdown":
            self.stopping = True
        else:
            self.emit({
                "protocolVersion": 1,
                "eventType": "engine.error",
                "recoverable": True,
                "message": f"Unsupported command: {kind}",
            })

    def run(self) -> int:
        self._reader.start()
        self.emit({
            "protocolVersion": 1,
            "eventType": "engine.ready",
            "pid": os.getpid(),
            "health": self.engine.health(),
        })
        next_snapshot = 0.0
        last_health = ""
        try:
            while not self.stopping:
                while True:
                    try:
                        self._handle(self.commands.get_nowait())
                    except queue.Empty:
                        break
                self.engine.poll()
                health = self.engine.health()
                encoded_health = json.dumps(health, sort_keys=True)
                if encoded_health != last_health:
                    self.emit({
                        "protocolVersion": 1,
                        "eventType": "engine.health",
                        "health": health,
                    })
                    last_health = encoded_health
                monotonic_now = time.monotonic()
                if monotonic_now >= next_snapshot:
                    self.emit(self.engine.snapshot_event())
                    next_snapshot = monotonic_now + SNAPSHOT_INTERVAL_SECONDS
                time.sleep(POLL_INTERVAL_SECONDS)
        except Exception as exc:
            self.emit({
                "protocolVersion": 1,
                "eventType": "engine.error",
                "recoverable": False,
                "message": f"{type(exc).__name__}: {exc}",
            })
            return 1
        finally:
            self.engine.close()
        return 0


def main() -> int:
    return JsonLineWorker().run()


if __name__ == "__main__":
    raise SystemExit(main())
