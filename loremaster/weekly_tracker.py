"""Durable D0-D4 raid lockout progress for the headless engine.

EverQuest Legends gives each raid boss five independent weekly loot-lockout
tracks.  The EQ text log identifies the defeated boss but does not reliably
state the selected difficulty, so difficulty is explicit caller evidence and
the tracker never guesses it from loot quality or combat strength.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PACIFIC_ZONE = "America/Los_Angeles"
RAID_RESET_WEEKDAY = 1  # Tuesday, Python Monday=0
RAID_RESET_HOUR = 8
DIFFICULTIES = tuple(range(5))
DIFFICULTY_NAMES = ("D0", "D1", "D2", "D3", "D4")


def normalize_target(value: str) -> str:
    value = re.sub(r"^(?:a|an|the)\s+", "", (value or "").strip(), flags=re.I)
    value = re.sub(r"[-_`'’]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


@dataclass(frozen=True, slots=True)
class BossTarget:
    name: str
    zone: str = ""
    aliases: tuple[str, ...] = ()


RAID_TARGETS: tuple[BossTarget, ...] = (
    BossTarget("Master Yael", "The Hole", ("Yael",)),
    BossTarget("Phinigel Autropos", "Kedge Keep", ("Phinigel", "Phinny")),
    BossTarget("Lord Nagafen", "Nagafen's Lair", ("Nagafen", "Naggy")),
    BossTarget("Lady Vox", "Permafrost Keep", ("Vox",)),
    BossTarget("Innoruuk", "Plane of Hate", ("Innoruuk (God)",)),
    BossTarget("Cazic-Thule", "Plane of Fear", (
        "Cazic Thule", "Cazic-Thule (God)", "Cazic Thule (God)", "Cazic")),
)


@dataclass(frozen=True, slots=True)
class BossKill:
    target: str
    zone: str
    character: str
    killed_at: str
    difficulty: int = 0
    duration_seconds: float = 0.0


def _pacific_zone():
    try:
        return ZoneInfo(PACIFIC_ZONE)
    except ZoneInfoNotFoundError:
        # Packaged builds include tzdata. This fallback keeps source builds
        # usable while remaining conservatively explicit about its limitation.
        return timezone(timedelta(hours=-8), "PST")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.astimezone()


def week_start(value: datetime, *, reset_weekday: int = RAID_RESET_WEEKDAY,
               reset_hour: int = RAID_RESET_HOUR,
               reset_zone: str = PACIFIC_ZONE) -> datetime:
    """Return the latest configured reset boundary as an aware datetime."""

    if not 0 <= reset_weekday <= 6:
        raise ValueError("reset_weekday must be between 0 and 6")
    if not 0 <= reset_hour <= 23:
        raise ValueError("reset_hour must be between 0 and 23")
    try:
        zone = ZoneInfo(reset_zone)
    except ZoneInfoNotFoundError:
        zone = _pacific_zone()
    local = _aware(value).astimezone(zone)
    boundary = local.replace(
        hour=reset_hour, minute=0, second=0, microsecond=0)
    boundary -= timedelta(days=(boundary.weekday() - reset_weekday) % 7)
    if local < boundary:
        boundary -= timedelta(days=7)
    return boundary


class WeeklyBossTracker:
    """Track one completion cell for each raid boss and D0-D4 tier."""

    def __init__(self, targets: Iterable[BossTarget] = RAID_TARGETS, *,
                 storage_path: str | Path | None = None,
                 reset_weekday: int = RAID_RESET_WEEKDAY,
                 reset_hour: int = RAID_RESET_HOUR,
                 reset_zone: str = PACIFIC_ZONE) -> None:
        self.targets = {normalize_target(item.name): item for item in targets}
        self.aliases: dict[str, str] = {}
        for key, target in self.targets.items():
            self.aliases[key] = key
            for alias in target.aliases:
                self.aliases[normalize_target(alias)] = key
        self.storage_path = Path(storage_path) if storage_path else None
        self.reset_weekday = reset_weekday
        self.reset_hour = reset_hour
        self.reset_zone = reset_zone
        self._kills: list[BossKill] = []
        self._load()

    def _load(self) -> None:
        if self.storage_path is None:
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
            self._kills = [BossKill(**row) for row in payload.get("kills", [])]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._kills = []

    def _save(self) -> None:
        if self.storage_path is None:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        temporary.write_text(json.dumps(
            {"schemaVersion": 2, "kills": [asdict(kill) for kill in self._kills]},
            indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, self.storage_path)

    def match_target(self, value: str) -> BossTarget | None:
        canonical = self.aliases.get(normalize_target(value))
        return self.targets.get(canonical) if canonical else None

    def _period_start(self, value: datetime) -> datetime:
        return week_start(
            value, reset_weekday=self.reset_weekday,
            reset_hour=self.reset_hour, reset_zone=self.reset_zone)

    @staticmethod
    def _kill_time(kill: BossKill) -> datetime | None:
        try:
            return _aware(datetime.fromisoformat(kill.killed_at))
        except ValueError:
            return None

    def _is_current(self, kill: BossKill, start: datetime, *,
                    character: str = "") -> bool:
        occurred_at = self._kill_time(kill)
        return bool(
            occurred_at is not None
            and occurred_at.astimezone(timezone.utc) >= start.astimezone(timezone.utc)
            and normalize_target(kill.target) in self.targets
            and (not character or kill.character.casefold() == character.casefold())
            and kill.difficulty in DIFFICULTIES)

    def observe_kill(self, occurred_at: datetime, target: str, *, zone: str,
                     character: str, difficulty: int,
                     duration_seconds: float = 0.0) -> bool:
        if difficulty not in DIFFICULTIES:
            raise ValueError("difficulty must be D0 through D4")
        definition = self.match_target(target)
        if definition is None:
            return False
        start = self._period_start(occurred_at)
        if any(
            self._is_current(kill, start, character=character)
            and normalize_target(kill.target) == normalize_target(definition.name)
            and kill.difficulty == difficulty
            for kill in self._kills
        ):
            return False
        stamp = _aware(occurred_at).astimezone(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z")
        self._kills.append(BossKill(
            target=definition.name,
            zone=zone or definition.zone,
            character=character or "?",
            killed_at=stamp,
            difficulty=difficulty,
            duration_seconds=max(0.0, round(float(duration_seconds), 3)),
        ))
        self._save()
        return True

    def set_completion(self, occurred_at: datetime, target: str,
                       difficulty: int, *, character: str,
                       completed: bool) -> bool:
        definition = self.match_target(target)
        if definition is None or difficulty not in DIFFICULTIES:
            return False
        if completed:
            return self.observe_kill(
                occurred_at, definition.name, zone=definition.zone,
                character=character, difficulty=difficulty)
        start = self._period_start(occurred_at)
        kept = [kill for kill in self._kills if not (
            self._is_current(kill, start, character=character)
            and normalize_target(kill.target) == normalize_target(definition.name)
            and kill.difficulty == difficulty)]
        changed = len(kept) != len(self._kills)
        if changed:
            self._kills = kept
            self._save()
        return changed

    def snapshot(self, now: datetime, *, character: str = "") -> dict:
        start = self._period_start(now)
        current = [kill for kill in self._kills
                   if self._is_current(kill, start, character=character)]
        completed = {
            (normalize_target(kill.target), kill.difficulty)
            for kill in current
        }
        raids = []
        for key, target in self.targets.items():
            best_seconds = []
            for difficulty in DIFFICULTIES:
                candidates = [
                    kill.duration_seconds for kill in self._kills
                    if normalize_target(kill.target) == key
                    and kill.difficulty == difficulty
                    and kill.duration_seconds > 0
                    and (not character or kill.character.casefold() == character.casefold())
                ]
                best_seconds.append(min(candidates) if candidates else None)
            raids.append({
                "target": target.name,
                "zone": target.zone,
                "difficulties": [
                    (key, difficulty) in completed
                    for difficulty in DIFFICULTIES
                ],
                "bestSeconds": best_seconds,
            })
        return {
            "weekStart": start.astimezone(timezone.utc).isoformat(
                timespec="seconds").replace("+00:00", "Z"),
            "nextReset": (start + timedelta(days=7)).astimezone(
                timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "resetLabel": "Tuesday 8:00 AM Pacific",
            "raidCount": len(self.targets),
            "trackedLockoutCount": len(self.targets) * len(DIFFICULTIES),
            "completedCount": len(completed),
            "kills": [asdict(kill) for kill in current],
            "raids": raids,
        }


__all__ = [
    "BossKill", "BossTarget", "DIFFICULTIES", "DIFFICULTY_NAMES",
    "PACIFIC_ZONE", "RAID_TARGETS", "WeeklyBossTracker", "normalize_target",
    "week_start",
]
