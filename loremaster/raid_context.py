"""Evidence-backed EverQuest Legends raid instance context.

Legends names instanced zones in the zone-entry log line itself, for example
``Nagafen's Lair - Solo 4 (Refined)``.  This module deliberately requires the
numeric tier and its label to agree before it exposes a difficulty.  Combat
strength, loot quality, and boss names are never used as substitutes for that
direct evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re


DIFFICULTY_LABELS: tuple[str, ...] = (
    "Normal", "Awakened", "Adaptive", "Fused", "Refined")
_LABEL_TO_DIFFICULTY = {
    label.casefold(): difficulty
    for difficulty, label in enumerate(DIFFICULTY_LABELS)
}
_INSTANCE_RE = re.compile(
    r"^(?P<zone>.+?)\s+-\s+(?P<mode>Solo|Group)\s+"
    r"(?P<difficulty>[0-4])\s+\((?P<label>"
    + "|".join(DIFFICULTY_LABELS)
    + r")\)$",
    re.IGNORECASE,
)
_NORMAL_INSTANCE_RE = re.compile(
    r"^(?P<zone>.+?)\s+-\s+(?P<mode>Solo|Group)$",
    re.IGNORECASE,
)
_ZONE_FALSE_POSITIVES = ("an area", "area where", "an arena")


def _utc_stamp(value: datetime | None) -> str:
    if value is None:
        return ""
    aware = value if value.tzinfo is not None else value.astimezone()
    return aware.astimezone(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def is_environmental_zone_message(zone_name: str) -> bool:
    """Return whether zone-like prose is not an actual zone transition."""

    folded = (zone_name or "").casefold()
    return any(marker in folded for marker in _ZONE_FALSE_POSITIVES)


@dataclass(frozen=True, slots=True)
class RaidInstanceContext:
    """One directly observed, internally consistent Legends instance name."""

    zone: str
    instance_name: str
    mode: str
    difficulty: int
    label: str
    observed_at: str = ""
    evidence: str = ""

    def snapshot(self) -> dict:
        return {
            "zone": self.zone,
            "instanceName": self.instance_name,
            "mode": self.mode,
            "difficulty": self.difficulty,
            "difficultyName": f"D{self.difficulty}",
            "label": self.label,
            "observedAt": self.observed_at,
            "evidence": self.evidence,
            "source": "log-zone",
        }

    def kill_evidence(self) -> dict:
        """Keyword evidence accepted by ``WeeklyBossTracker.observe_kill``."""

        return {
            "difficulty_source": "log-zone",
            "instance_name": self.instance_name,
            "instance_mode": self.mode,
            "instance_label": self.label,
            "context_observed_at": self.observed_at,
            "evidence": self.evidence,
        }


def parse_raid_instance(zone_name: str, *, occurred_at: datetime | None = None,
                        evidence: str = "") -> RaidInstanceContext | None:
    """Parse direct D0-D4 instance evidence, rejecting inconsistent labels."""

    value = (zone_name or "").strip()
    match = _INSTANCE_RE.fullmatch(value)
    if match is None:
        # Legends omits both the numeric suffix and parenthetical label for a
        # D0 instance ("Nagafen's Lair - Solo"). A completely bare zone name
        # remains open world and must never be guessed as D0.
        normal_match = _NORMAL_INSTANCE_RE.fullmatch(value)
        if normal_match is None:
            return None
        match = normal_match
        difficulty = 0
        label = DIFFICULTY_LABELS[0]
    else:
        difficulty = int(match.group("difficulty"))
        label_difficulty = _LABEL_TO_DIFFICULTY[
            match.group("label").casefold()]
        if difficulty != label_difficulty:
            # Treat inconsistent text as unknown rather than guessing which
            # half was intended. This protects against future naming changes.
            return None
        label = DIFFICULTY_LABELS[difficulty]
    mode = match.group("mode").capitalize()
    return RaidInstanceContext(
        zone=match.group("zone").strip(),
        instance_name=value,
        mode=mode,
        difficulty=difficulty,
        label=label,
        observed_at=_utc_stamp(occurred_at),
        evidence=(evidence or f"You have entered {value}.").strip(),
    )


class RaidContextTracker:
    """Hold only the context established by the latest real zone entry."""

    def __init__(self) -> None:
        self.active: RaidInstanceContext | None = None

    def clear(self) -> None:
        self.active = None

    def observe_zone(self, zone_name: str, *, occurred_at: datetime | None = None,
                     evidence: str = "") -> RaidInstanceContext | None:
        if is_environmental_zone_message(zone_name):
            return self.active
        # A plain real zone entry is authoritative evidence that the previous
        # instance context no longer applies, even when the new zone is itself
        # a raid's open-world version.
        self.active = parse_raid_instance(
            zone_name, occurred_at=occurred_at, evidence=evidence)
        return self.active

    def snapshot(self) -> dict | None:
        return self.active.snapshot() if self.active is not None else None


__all__ = [
    "DIFFICULTY_LABELS", "RaidContextTracker", "RaidInstanceContext",
    "is_environmental_zone_message", "parse_raid_instance",
]
