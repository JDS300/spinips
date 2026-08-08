"""Versioned, renderer-neutral Loremaster engine snapshots.

The Python parser remains the source of truth.  These frozen value objects are
the narrow boundary consumed by the Electron fixture preview and, later, a
supervised local worker connection.  No Tk widgets or mutable parser objects
cross this boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any


PROTOCOL_VERSION = 1


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class CharacterView:
    name: str
    level: int
    composition: str
    zone: str


@dataclass(frozen=True)
class CombatView:
    active: bool
    encounter_name: str
    fight_dps: int
    session_dps: int
    personal_damage: int
    charmed_pet_damage: int
    summoned_pet_damage: int
    fight_seconds: float
    fight_damage: int
    fight_personal_damage: int
    fight_charmed_pet_damage: int
    fight_summoned_pet_damage: int
    damage_taken: int
    healing_done: int
    kills: int
    crits: int
    misses: int


@dataclass(frozen=True)
class CombatMetricView:
    name: str
    total: int
    hits: int
    maximum: int


@dataclass(frozen=True)
class CombatBreakdownView:
    sources: tuple[CombatMetricView, ...]
    targets: tuple[CombatMetricView, ...]
    actors: tuple[CombatMetricView, ...]


@dataclass(frozen=True)
class ControlTimerView:
    kind: str
    state: str
    target: str
    count: int
    spell: str
    rank: int
    landed_at: str
    safe_expires_at: str
    expires_at: str
    duration_seconds: int
    safe_remaining_seconds: float
    remaining_seconds: float
    last_tick: bool
    urgency: str
    confidence: str
    ambiguity: str


@dataclass(frozen=True)
class EngineSnapshot:
    protocol_version: int
    sequence: int
    observed_at: str
    character: CharacterView
    combat: CombatView
    breakdown: CombatBreakdownView
    controls: tuple[ControlTimerView, ...]
    hidden_control_rows: int
    control_notice_count: int
    control_ambiguity_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"),
            sort_keys=True)


@dataclass(frozen=True)
class EngineEvent:
    protocol_version: int
    sequence: int
    occurred_at: str
    event_type: str
    snapshot: EngineSnapshot

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # JSON-facing names stay stable and idiomatic for TypeScript.
        payload["protocolVersion"] = payload.pop("protocol_version")
        payload["occurredAt"] = payload.pop("occurred_at")
        payload["eventType"] = payload.pop("event_type")
        snapshot = payload["snapshot"]
        snapshot["protocolVersion"] = snapshot.pop("protocol_version")
        snapshot["observedAt"] = snapshot.pop("observed_at")
        snapshot["hiddenControlRows"] = snapshot.pop("hidden_control_rows")
        snapshot["controlNoticeCount"] = snapshot.pop("control_notice_count")
        snapshot["controlAmbiguityCount"] = snapshot.pop(
            "control_ambiguity_count")
        for control in snapshot["controls"]:
            control["landedAt"] = control.pop("landed_at")
            control["safeExpiresAt"] = control.pop("safe_expires_at")
            control["expiresAt"] = control.pop("expires_at")
            control["durationSeconds"] = control.pop("duration_seconds")
            control["safeRemainingSeconds"] = control.pop(
                "safe_remaining_seconds")
            control["remainingSeconds"] = control.pop("remaining_seconds")
            control["lastTick"] = control.pop("last_tick")
        combat = snapshot["combat"]
        for old, new in (
                ("encounter_name", "encounterName"),
                ("fight_dps", "fightDps"),
                ("session_dps", "sessionDps"),
                ("personal_damage", "personalDamage"),
                ("charmed_pet_damage", "charmedPetDamage"),
                ("summoned_pet_damage", "summonedPetDamage")):
            combat[new] = combat.pop(old)
        combat["fightSeconds"] = combat.pop("fight_seconds")
        for old, new in (
                ("fight_damage", "fightDamage"),
                ("fight_personal_damage", "fightPersonalDamage"),
                ("fight_charmed_pet_damage", "fightCharmedPetDamage"),
                ("fight_summoned_pet_damage", "fightSummonedPetDamage"),
                ("damage_taken", "damageTaken"),
                ("healing_done", "healingDone")):
            combat[new] = combat.pop(old)
        return payload

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"),
            sort_keys=True)


def build_engine_snapshot(*, sequence: int, observed_at: datetime,
                          stats_snapshot: dict,
                          control_snapshot) -> EngineSnapshot:
    """Copy mutable runtime dictionaries into one frozen boundary snapshot."""

    controls = tuple(ControlTimerView(
        kind=row.control_kind,
        state=row.timer_state,
        target=row.target_name,
        count=int(row.count),
        spell=row.spell_name,
        rank=int(row.rank),
        landed_at=_timestamp(row.landed_at),
        safe_expires_at=_timestamp(row.safe_expires_at),
        expires_at=_timestamp(row.expires_at),
        duration_seconds=int(row.duration_seconds),
        safe_remaining_seconds=round(float(row.safe_remaining_seconds), 3),
        remaining_seconds=round(float(row.remaining_seconds), 3),
        last_tick=bool(row.last_tick),
        urgency=row.urgency,
        confidence=row.confidence,
        ambiguity=row.ambiguity,
    ) for row in control_snapshot.rows)
    fight = stats_snapshot.get("fight")
    if isinstance(fight, dict):
        encounter_name = str(fight.get("name") or "")
        fight_dps = int(fight.get("dps") or 0)
        fight_seconds = float(fight.get("seconds") or 0.0)
        fight_damage = int(fight.get("damage") or 0)
        fight_charmed = int(fight.get("charmed_pet_damage") or 0)
        fight_summoned = int(fight.get("summoned_pet_damage") or 0)
        damage_taken = int(fight.get("damage_taken") or 0)
        healing_done = int(fight.get("healing_done") or 0)
        kills = int(fight.get("kills") or 0)
        crits = int(fight.get("crits") or 0)
        misses = int(fight.get("misses") or 0)
    else:
        encounter_name = str(getattr(fight, "name", "") or "")
        fight_dps = int(getattr(fight, "dps", 0) or 0)
        fight_seconds = float(getattr(fight, "seconds", 0.0) or 0.0)
        fight_damage = int(getattr(fight, "damage", 0) or 0)
        fight_charmed = int(getattr(fight, "charmed_pet_damage", 0) or 0)
        fight_summoned = int(getattr(fight, "summoned_pet_damage", 0) or 0)
        damage_taken = int(getattr(fight, "damage_taken", 0) or 0)
        healing_done = int(getattr(fight, "healing_done", 0) or 0)
        kills = int(getattr(fight, "kills", 0) or 0)
        crits = int(getattr(fight, "crits", 0) or 0)
        misses = int(getattr(fight, "misses", 0) or 0)

    def metric_rows(values, *, plain_totals=False) -> tuple[CombatMetricView, ...]:
        rows = []
        for name, value in (values or {}).items():
            if plain_totals:
                total, hits, maximum = int(value or 0), 0, 0
            else:
                total = int(value.get("t") or 0) if isinstance(value, dict) else int(value or 0)
                hits = int(value.get("h") or 0) if isinstance(value, dict) else 0
                maximum = int(value.get("max") or 0) if isinstance(value, dict) else 0
            rows.append(CombatMetricView(str(name), total, hits, maximum))
        return tuple(sorted(rows, key=lambda row: (-row.total, row.name.casefold()))[:12])

    breakdown = CombatBreakdownView(
        sources=metric_rows(stats_snapshot.get("fight_sources")),
        targets=metric_rows(stats_snapshot.get("fight_targets"), plain_totals=True),
        actors=metric_rows(stats_snapshot.get("fight_actor_damage")),
    )
    personal_damage = stats_snapshot.get("personal_damage")
    if personal_damage is None:
        personal_damage = max(
            0,
            int(stats_snapshot.get("combat_damage") or 0)
            - int(stats_snapshot.get("pet_damage") or 0),
        )
    return EngineSnapshot(
        protocol_version=PROTOCOL_VERSION,
        sequence=max(0, int(sequence)),
        observed_at=_timestamp(observed_at),
        character=CharacterView(
            name=str(stats_snapshot.get("character") or "?"),
            level=int(stats_snapshot.get("level") or 0),
            composition=str(stats_snapshot.get("composition") or ""),
            zone=str(stats_snapshot.get("zone") or ""),
        ),
        combat=CombatView(
            active=bool(stats_snapshot.get("in_combat", False)),
            encounter_name=encounter_name,
            fight_dps=fight_dps,
            session_dps=int(stats_snapshot.get("session_dps") or 0),
            personal_damage=int(personal_damage or 0),
            charmed_pet_damage=int(
                stats_snapshot.get("charmed_pet_damage") or 0),
            summoned_pet_damage=int(
                stats_snapshot.get("summoned_pet_damage") or 0),
            fight_seconds=round(fight_seconds, 3),
            fight_damage=fight_damage,
            fight_personal_damage=max(0, fight_damage - fight_charmed - fight_summoned),
            fight_charmed_pet_damage=fight_charmed,
            fight_summoned_pet_damage=fight_summoned,
            damage_taken=damage_taken,
            healing_done=healing_done,
            kills=kills,
            crits=crits,
            misses=misses,
        ),
        breakdown=breakdown,
        controls=controls,
        hidden_control_rows=int(control_snapshot.hidden_rows),
        control_notice_count=int(control_snapshot.notice_count),
        control_ambiguity_count=int(control_snapshot.ambiguity_count),
    )


def snapshot_event(snapshot: EngineSnapshot) -> EngineEvent:
    return EngineEvent(
        protocol_version=PROTOCOL_VERSION,
        sequence=snapshot.sequence,
        occurred_at=snapshot.observed_at,
        event_type="engine.snapshot",
        snapshot=snapshot,
    )


__all__ = [
    "PROTOCOL_VERSION",
    "CharacterView",
    "CombatView",
    "CombatMetricView",
    "CombatBreakdownView",
    "ControlTimerView",
    "EngineEvent",
    "EngineSnapshot",
    "build_engine_snapshot",
    "snapshot_event",
]
