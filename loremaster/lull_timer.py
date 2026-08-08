"""Evidence-first lull and pacification tracking for Loremaster.

EverQuest exposes no stable NPC identifiers and several lull-family spells do
not emit a success line.  This tracker therefore starts an active countdown
only after a recognized local cast is correlated with an observable landing.
Silent spells remain explicitly unconfirmed instead of being promoted to a
guessed timer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import ceil
import re
from typing import Iterable

from mez_timer import (
    DEFAULT_CRITICAL_SECONDS,
    DEFAULT_WARNING_SECONDS,
    SERVER_TICK_SECONDS,
    mez_urgency,
    scaled_duration_ticks,
    split_spell_rank,
)


MIN_CORRELATION_SECONDS = 2.0
CORRELATION_SLACK_SECONDS = 1.0
NOTICE_SECONDS = 8.0


@dataclass(frozen=True)
class LullSpell:
    """One supported lull-family spell from the EQL spell data."""

    name: str
    duration_formula: int
    duration_cap_ticks: int
    base_cast_seconds: float
    area: bool = False
    result_visible: bool = True
    aliases: tuple[str, ...] = ()


LULL_SPELLS: tuple[LullSpell, ...] = (
    LullSpell("Pacify", 8, 7, 3.0),
    LullSpell("Calm", 8, 7, 2.5),
    LullSpell("Lull", 9, 20, 1.5),
    # EQL's spell strings contain no target landing line for these two.
    LullSpell("Lull Animal", 9, 20, 1.5, result_visible=False),
    LullSpell("Harmony", 2, 20, 3.0, area=True, result_visible=False),
    LullSpell("Soothe", 8, 25, 2.0),
    LullSpell("Calm Animal", 8, 7, 2.5),
    LullSpell("Pacification", 8, 7, 4.5),
)


@dataclass(frozen=True)
class ResolvedLullSpell:
    spell: LullSpell
    rank: int
    caster_level: int | None
    duration_ticks: int
    duration_seconds: int
    safe_duration_seconds: int
    cast_seconds: float
    duration_confidence: str

    @property
    def name(self) -> str:
        return self.spell.name

    @property
    def area(self) -> bool:
        return self.spell.area


@dataclass(frozen=True)
class PendingLullCast:
    cast_id: int
    resolved: ResolvedLullSpell
    began_at: datetime
    landed_count: int = 0
    first_landed_at: datetime | None = None


@dataclass(frozen=True)
class LullRow:
    target_name: str
    count: int
    spell_name: str
    rank: int
    landed_at: datetime
    safe_expires_at: datetime
    expires_at: datetime
    duration_seconds: int
    safe_remaining_seconds: float
    remaining_seconds: float
    last_tick: bool
    urgency: str
    control_kind: str = "lull"
    confidence: str = "confirmed"
    ambiguity: str = ""


@dataclass(frozen=True)
class LullNotice:
    spell_name: str
    rank: int
    status: str
    detail: str
    observed_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class LullSnapshot:
    rows: tuple[LullRow, ...]
    notices: tuple[LullNotice, ...]
    hidden_rows: int
    group_count: int
    active_count: int


@dataclass(frozen=True)
class LullWarningEvent:
    target_name: str
    count: int
    spell_name: str
    safe_expires_at: datetime
    remaining_seconds: float


@dataclass
class _ActiveLull:
    timer_id: int
    cast_id: int
    target_name: str
    resolved: ResolvedLullSpell
    landed_at: datetime
    safe_expires_at: datetime
    expires_at: datetime


_APOSTROPHE_TRANSLATION = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u02bc": "'",
    "`": "'",
})


def _name_key(value: str | None) -> str:
    text = (value or "").translate(_APOSTROPHE_TRANSLATION).casefold()
    text = text.replace("'", "")
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


_SPELL_BY_KEY: dict[str, LullSpell] = {}
for _spell in LULL_SPELLS:
    for _alias in (_spell.name, *_spell.aliases):
        _SPELL_BY_KEY[_name_key(_alias)] = _spell


def duration_formula_ticks(formula: int, caster_level: int) -> int:
    """Evaluate the classic EQ tick formulas used by supported lulls."""

    level = max(1, int(caster_level))
    if formula == 2:
        return level // 2 + 5
    if formula == 8:
        return level + 10
    if formula == 9:
        return level * 2 + 10
    raise ValueError(f"unsupported lull duration formula: {formula}")


def resolve_lull_spell(
        spell_name: str | None,
        caster_level: int | None = None,
) -> ResolvedLullSpell | None:
    """Resolve a lull spell and calculate an honest, conservative duration."""

    if not spell_name:
        return None
    base_name, rank = split_spell_rank(spell_name)
    spell = _SPELL_BY_KEY.get(_name_key(base_name))
    if spell is None:
        return None
    known_level = None
    try:
        if caster_level is not None and int(caster_level) > 0:
            known_level = int(caster_level)
    except (TypeError, ValueError):
        known_level = None
    # Without a logged level, use level one as a strict lower bound. This can
    # shorten a displayed safe window, never lengthen it beyond evidence.
    formula_level = known_level or 1
    base_ticks = min(
        duration_formula_ticks(spell.duration_formula, formula_level),
        spell.duration_cap_ticks,
    )
    exact_without_level = duration_formula_ticks(
        spell.duration_formula, 1) >= spell.duration_cap_ticks
    confidence = (
        "exact" if known_level is not None or exact_without_level
        else "conservative"
    )
    ticks = scaled_duration_ticks(base_ticks, rank)
    full_seconds = ticks * SERVER_TICK_SECONDS
    # The final server tick is not advertised as guaranteed safe time.
    safe_seconds = max(0, full_seconds - SERVER_TICK_SECONDS)
    cast_scale = 1.0 - 0.04 * min(10, max(0, rank))
    return ResolvedLullSpell(
        spell=spell,
        rank=rank,
        caster_level=known_level,
        duration_ticks=ticks,
        duration_seconds=full_seconds,
        safe_duration_seconds=safe_seconds,
        cast_seconds=spell.base_cast_seconds * cast_scale,
        duration_confidence=confidence,
    )


class LullTracker:
    """Correlate local lull casts with visible results and failures."""

    def __init__(self, *, pending_seconds: float = 7.0,
                 area_landing_seconds: float = 1.25) -> None:
        if pending_seconds <= 0:
            raise ValueError("pending_seconds must be positive")
        if area_landing_seconds <= 0:
            raise ValueError("area_landing_seconds must be positive")
        self.pending_seconds = float(pending_seconds)
        self.area_landing_seconds = float(area_landing_seconds)
        self._pending: PendingLullCast | None = None
        self._nearby_pending: PendingLullCast | None = None
        self._groups: dict[str, list[_ActiveLull]] = {}
        self._notices: list[LullNotice] = []
        self._skip_ambiguous_landing = False
        self._next_cast_id = 1
        self._next_timer_id = 1
        self._warned_timer_ids: set[int] = set()

    @property
    def pending(self) -> PendingLullCast | None:
        return self._pending

    def _notice(self, resolved: ResolvedLullSpell, occurred_at: datetime,
                status: str, detail: str) -> None:
        self._notices.append(LullNotice(
            spell_name=resolved.name,
            rank=resolved.rank,
            status=status,
            detail=detail,
            observed_at=occurred_at,
            expires_at=occurred_at + timedelta(seconds=NOTICE_SECONDS),
        ))

    def begin_cast(self, spell_name: str, occurred_at: datetime,
                   caster_level: int | None = None) -> PendingLullCast | None:
        resolved = resolve_lull_spell(spell_name, caster_level)
        if resolved is None:
            self._pending = None
            self._nearby_pending = None
            self._skip_ambiguous_landing = False
            return None
        if self._pending is not None:
            self._notice(
                self._pending.resolved, occurred_at, "unconfirmed",
                "A newer local cast closed the pending result window",
            )
        nearby = self._nearby_pending
        self._skip_ambiguous_landing = bool(
            nearby is not None and nearby.began_at <= occurred_at
            and occurred_at <= self._pending_deadline(nearby)
        )
        if self._skip_ambiguous_landing:
            self._notice(
                resolved, occurred_at, "ambiguous",
                "A nearby lull cast overlaps this result window; no timer",
            )
        self._nearby_pending = None
        pending = PendingLullCast(self._next_cast_id, resolved, occurred_at)
        self._next_cast_id += 1
        self._pending = pending
        if not resolved.spell.result_visible:
            self._notice(
                resolved, occurred_at, "unconfirmed",
                "This spell has no landing line in EQL; cast observed, no timer",
            )
        return pending

    def observe_nearby_cast(self, spell_name: str, occurred_at: datetime,
                            caster_level: int | None = None) -> bool:
        resolved = resolve_lull_spell(spell_name, caster_level)
        if resolved is None:
            return False
        if self._pending is not None:
            self._notice(
                self._pending.resolved, occurred_at, "ambiguous",
                "Nearby lull cast made the landing ownership ambiguous",
            )
            self._pending = None
            self._skip_ambiguous_landing = False
        self._nearby_pending = PendingLullCast(0, resolved, occurred_at)
        return True

    def _pending_deadline(self, pending: PendingLullCast) -> datetime:
        seconds = max(
            MIN_CORRELATION_SECONDS,
            ceil(pending.resolved.cast_seconds) + CORRELATION_SLACK_SECONDS,
        )
        if pending.first_landed_at is not None:
            seconds = min(
                seconds,
                (pending.first_landed_at - pending.began_at).total_seconds()
                + self.area_landing_seconds,
            )
        return pending.began_at + timedelta(
            seconds=min(self.pending_seconds, seconds))

    def _prune(self, now: datetime) -> None:
        self._notices = [notice for notice in self._notices
                         if notice.expires_at > now]
        pending = self._pending
        if pending is not None and now > self._pending_deadline(pending):
            if pending.resolved.spell.result_visible:
                self._notice(
                    pending.resolved, now, "unconfirmed",
                    "No compatible landing result was logged; no timer",
                )
            self._pending = None
            self._skip_ambiguous_landing = False
        if (self._nearby_pending is not None
                and now > self._pending_deadline(self._nearby_pending)):
            self._nearby_pending = None
        for key in list(self._groups):
            live = [entry for entry in self._groups[key]
                    if entry.expires_at > now]
            for entry in self._groups[key]:
                if entry not in live:
                    self._warned_timer_ids.discard(entry.timer_id)
            if live:
                self._groups[key] = live
            else:
                del self._groups[key]

    def cancel_pending(self, occurred_at: datetime, status: str,
                       detail: str, spell_name: str | None = None) -> bool:
        pending = self._pending
        if pending is None:
            return False
        if spell_name:
            resolved = resolve_lull_spell(
                spell_name, pending.resolved.caster_level)
            if resolved is None or resolved.name != pending.resolved.name:
                return False
        self._notices = [
            notice for notice in self._notices
            if not (notice.spell_name == pending.resolved.name
                    and notice.status == "unconfirmed"
                    and notice.observed_at == pending.began_at)
        ]
        self._notice(pending.resolved, occurred_at, status, detail)
        self._pending = None
        self._skip_ambiguous_landing = False
        return True

    def observe_fizzle(self, occurred_at: datetime) -> bool:
        return self.cancel_pending(
            occurred_at, "failed", "Spell fizzled; no timer")

    def observe_interrupt(self, occurred_at: datetime) -> bool:
        return self.cancel_pending(
            occurred_at, "failed", "Cast interrupted; no timer")

    def observe_resist(self, occurred_at: datetime,
                       spell_name: str | None = None) -> bool:
        return self.cancel_pending(
            occurred_at, "failed", "Target resisted; no timer", spell_name)

    def observe_unattributed_landing(self, occurred_at: datetime) -> None:
        pending = self._pending
        if pending is not None:
            self._notice(
                pending.resolved, occurred_at, "ambiguous",
                "Unowned lull result ignored; no timer",
            )
            self._pending = None
            self._skip_ambiguous_landing = False
        self._nearby_pending = None

    def observe_landing(self, target_name: str,
                        occurred_at: datetime) -> LullRow | None:
        display_target = " ".join((target_name or "").strip().split())
        if not display_target:
            return None
        self._prune(occurred_at)
        pending = self._pending
        if (pending is None or occurred_at < pending.began_at
                or not pending.resolved.spell.result_visible):
            return None
        if self._skip_ambiguous_landing:
            self._notice(
                pending.resolved, occurred_at, "ambiguous",
                "Overlapping nearby lull result ignored; no timer",
            )
            self._pending = None
            self._skip_ambiguous_landing = False
            return None
        key = _name_key(display_target)
        entries = self._groups.setdefault(key, [])
        candidates = [entry for entry in entries
                      if entry.cast_id != pending.cast_id]
        safe_expires_at = occurred_at + timedelta(
            seconds=pending.resolved.safe_duration_seconds)
        expires_at = occurred_at + timedelta(
            seconds=pending.resolved.duration_seconds)
        if candidates:
            active = min(candidates, key=lambda entry: entry.expires_at)
            self._warned_timer_ids.discard(active.timer_id)
            active.cast_id = pending.cast_id
            active.target_name = display_target
            active.resolved = pending.resolved
            active.landed_at = occurred_at
            active.safe_expires_at = safe_expires_at
            active.expires_at = expires_at
        else:
            active = _ActiveLull(
                timer_id=self._next_timer_id,
                cast_id=pending.cast_id,
                target_name=display_target,
                resolved=pending.resolved,
                landed_at=occurred_at,
                safe_expires_at=safe_expires_at,
                expires_at=expires_at,
            )
            self._next_timer_id += 1
            entries.append(active)
        landed_count = pending.landed_count + 1
        if pending.resolved.area:
            self._pending = replace(
                pending,
                landed_count=landed_count,
                first_landed_at=pending.first_landed_at or occurred_at,
            )
        else:
            self._pending = None
        return self._row_for_group(entries, occurred_at)

    def _pop_one(self, target_name: str,
                 occurred_at: datetime) -> _ActiveLull | None:
        self._prune(occurred_at)
        key = _name_key(target_name)
        entries = self._groups.get(key)
        if not entries:
            return None
        removed = min(entries, key=lambda entry: entry.safe_expires_at)
        entries.remove(removed)
        self._warned_timer_ids.discard(removed.timer_id)
        if not entries:
            del self._groups[key]
        return removed

    def observe_damage(self, target_name: str, occurred_at: datetime) -> bool:
        """Retire a lull row once the actor is visibly engaged or damaged."""

        return self._pop_one(target_name, occurred_at) is not None

    def observe_kill(self, target_name: str, occurred_at: datetime) -> bool:
        return self._pop_one(target_name, occurred_at) is not None

    def _matching_candidate(
            self, target_name: str | None, occurred_at: datetime,
            spell_name: str | None = None,
    ) -> tuple[list[_ActiveLull], _ActiveLull, str] | None:
        self._prune(occurred_at)
        resolved = resolve_lull_spell(spell_name) if spell_name else None
        if spell_name and resolved is None:
            return None
        display_target = " ".join((target_name or "").strip().split())
        candidates: list[_ActiveLull]
        if display_target:
            key = _name_key(display_target)
            entries = self._groups.get(key)
            if not entries:
                return None
            candidates = entries
        else:
            candidates = [entry for entries in self._groups.values()
                          for entry in entries]
            if not candidates:
                return None
            key = ""
            entries = []
        if resolved is not None:
            candidates = [entry for entry in candidates
                          if entry.resolved.name == resolved.name]
            if not candidates:
                return None
        removed = min(candidates, key=lambda entry: entry.safe_expires_at)
        if not key:
            key = _name_key(removed.target_name)
            entries = self._groups[key]
        return entries, removed, key

    def _discard_candidate(self, entries: list[_ActiveLull],
                           removed: _ActiveLull, key: str) -> None:
        entries.remove(removed)
        self._warned_timer_ids.discard(removed.timer_id)
        if not entries:
            del self._groups[key]

    def observe_fade(self, target_name: str | None, occurred_at: datetime,
                     spell_name: str | None = None) -> bool:
        candidate = self._matching_candidate(
            target_name, occurred_at, spell_name)
        if candidate is None:
            return False
        self._discard_candidate(*candidate)
        return True

    def observe_overwrite(self, target_name: str | None,
                          occurred_at: datetime,
                          spell_name: str | None = None) -> bool:
        return self.observe_fade(target_name, occurred_at, spell_name)

    def clear(self) -> int:
        count = sum(len(entries) for entries in self._groups.values())
        self._pending = None
        self._nearby_pending = None
        self._groups.clear()
        self._notices.clear()
        self._skip_ambiguous_landing = False
        self._warned_timer_ids.clear()
        return count

    @staticmethod
    def _row_for_group(
            entries: Iterable[_ActiveLull], now: datetime,
            warning_seconds: float = DEFAULT_WARNING_SECONDS,
            critical_seconds: float = DEFAULT_CRITICAL_SECONDS,
    ) -> LullRow:
        grouped = tuple(entries)
        earliest = min(grouped, key=lambda entry: entry.safe_expires_at)
        safe_remaining = max(0.0, (
            earliest.safe_expires_at - now).total_seconds())
        remaining = max(0.0, (
            earliest.expires_at - now).total_seconds())
        return LullRow(
            target_name=earliest.target_name,
            count=len(grouped),
            spell_name=earliest.resolved.name,
            rank=earliest.resolved.rank,
            landed_at=earliest.landed_at,
            safe_expires_at=earliest.safe_expires_at,
            expires_at=earliest.expires_at,
            duration_seconds=earliest.resolved.safe_duration_seconds,
            safe_remaining_seconds=safe_remaining,
            remaining_seconds=remaining,
            last_tick=now >= earliest.safe_expires_at,
            urgency=mez_urgency(
                safe_remaining,
                warning_seconds=warning_seconds,
                critical_seconds=critical_seconds,
            ),
            confidence=earliest.resolved.duration_confidence,
            ambiguity=(
                f"earliest expiry of {len(grouped)} same-name targets"
                if len(grouped) > 1 else ""
            ),
        )

    def snapshot(self, now: datetime, *, limit: int | None = 3,
                 warning_seconds: float = DEFAULT_WARNING_SECONDS,
                 critical_seconds: float = DEFAULT_CRITICAL_SECONDS,
                 include_notices: bool = True) -> LullSnapshot:
        if limit is not None and limit < 0:
            raise ValueError("limit cannot be negative")
        self._prune(now)
        rows = [self._row_for_group(
            entries, now, warning_seconds, critical_seconds)
            for entries in self._groups.values()]
        rows.sort(key=lambda row: (
            row.safe_expires_at, row.target_name.casefold()))
        visible = rows if limit is None else rows[:limit]
        hidden = 0 if limit is None else max(0, len(rows) - limit)
        notices = tuple(self._notices[-2:]) if include_notices else ()
        return LullSnapshot(
            rows=tuple(visible),
            notices=notices,
            hidden_rows=hidden,
            group_count=len(rows),
            active_count=sum(len(entries) for entries in self._groups.values()),
        )

    def pop_warning_events(self, now: datetime, *,
                           threshold_seconds: float = DEFAULT_WARNING_SECONDS,
                           enabled: bool = True) -> tuple[LullWarningEvent, ...]:
        if not enabled or threshold_seconds <= 0:
            return ()
        self._prune(now)
        events: list[LullWarningEvent] = []
        for entries in self._groups.values():
            earliest = min(entries, key=lambda entry: entry.safe_expires_at)
            remaining = max(0.0, (
                earliest.safe_expires_at - now).total_seconds())
            if (remaining <= threshold_seconds
                    and earliest.timer_id not in self._warned_timer_ids):
                self._warned_timer_ids.add(earliest.timer_id)
                events.append(LullWarningEvent(
                    target_name=earliest.target_name,
                    count=len(entries),
                    spell_name=earliest.resolved.name,
                    safe_expires_at=earliest.safe_expires_at,
                    remaining_seconds=remaining,
                ))
        events.sort(key=lambda event: (
            event.safe_expires_at, event.target_name.casefold()))
        return tuple(events)


__all__ = [
    "LULL_SPELLS",
    "LullNotice",
    "LullRow",
    "LullSnapshot",
    "LullSpell",
    "LullTracker",
    "LullWarningEvent",
    "PendingLullCast",
    "ResolvedLullSpell",
    "duration_formula_ticks",
    "resolve_lull_spell",
]
