"""Tk-free mez duration tracking for Loremaster.

EverQuest log lines do not expose stable NPC actor IDs.  This module therefore
correlates a recognized *local* cast with its landing line, then groups actors
that have the same visible name.  A grouped row always reports its earliest
expiry, which is the conservative timer when two identical creatures cannot be
distinguished.

The tracker deliberately has no dependency on the combat parser or DPS state.
Callers decide which begin-cast, landing, damage, death, and fade log events
belong here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import ceil
import re
from typing import Iterable


DEFAULT_WARNING_SECONDS = 10.0
DEFAULT_CRITICAL_SECONDS = 5.0
SERVER_TICK_SECONDS = 6
MIN_CORRELATION_SECONDS = 2.0
CORRELATION_SLACK_SECONDS = 1.0
WAKE_SIGNAL_DEDUPE_SECONDS = 1.5
AMBIGUITY_NOTICE_SECONDS = 8.0


@dataclass(frozen=True)
class MezSpell:
    """A verified base-rank mez duration measured in six-second EQ ticks."""

    name: str
    base_ticks: int
    base_cast_seconds: float
    area: bool = False
    aliases: tuple[str, ...] = ()
    landing_family: str = "mesmerized"


MEZ_SPELLS: tuple[MezSpell, ...] = (
    MezSpell("Mesmerize", 4, 2.5),
    MezSpell("Enthrall", 8, 2.5, landing_family="enthralled"),
    MezSpell("Mesmerization", 4, 3.0, area=True),
    MezSpell("Entrancing Lights", 1, 1.5, area=True,
             landing_family="lights"),
    MezSpell("Entrance", 12, 2.5, landing_family="entranced"),
    MezSpell("Dazzle", 16, 2.5),
    MezSpell("Fascination", 6, 3.0, area=True,
             landing_family="fascinated"),
    # spells_us.txt uses a level-based duration capped at these values; both
    # spells are learned above the level needed to reach their cap.
    MezSpell("Glamour of Kintaz", 9, 2.5, landing_family="glamour"),
    MezSpell("Rapture", 7, 2.5, landing_family="rapture"),
    MezSpell("Screaming Terror", 3, 2.6, landing_family="screaming"),
    MezSpell("Kelin's Lucid Lullaby", 3, 3.0,
             landing_family="lullaby"),
    MezSpell("Crission's Pixie Strike", 3, 3.0,
             landing_family="pixie"),
    MezSpell("Sionachie's Dreams", 3, 3.0,
             landing_family="pixie"),
)


@dataclass(frozen=True)
class ResolvedMezSpell:
    """A spell name resolved to its base entry, upgrade rank, and duration."""

    spell: MezSpell
    rank: int
    duration_ticks: int
    duration_seconds: int
    cast_seconds: float

    @property
    def name(self) -> str:
        return self.spell.name

    @property
    def area(self) -> bool:
        return self.spell.area


@dataclass(frozen=True)
class PendingMezCast:
    """A local mez cast waiting for one or more confirmed landing lines."""

    cast_id: int
    resolved: ResolvedMezSpell
    began_at: datetime
    landed_count: int = 0
    first_landed_at: datetime | None = None


@dataclass(frozen=True)
class MezRow:
    """One display row, possibly representing several same-named creatures."""

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
    control_kind: str = "mez"
    confidence: str = "confirmed"
    ambiguity: str = ""


@dataclass(frozen=True)
class MezSnapshot:
    """An immutable, urgency-sorted view suitable for a compact UI."""

    rows: tuple[MezRow, ...]
    hidden_rows: int
    group_count: int
    active_count: int
    ambiguity_note: str = ""
    ambiguity_count: int = 0
    ambiguity_observed_at: datetime | None = None
    ambiguity_until: datetime | None = None


@dataclass(frozen=True)
class MezWarningEvent:
    """A one-shot warning that the earliest timer for a group is nearly done."""

    target_name: str
    count: int
    spell_name: str
    safe_expires_at: datetime
    remaining_seconds: float


@dataclass
class _ActiveMez:
    timer_id: int
    cast_id: int
    target_name: str
    resolved: ResolvedMezSpell
    landed_at: datetime
    safe_expires_at: datetime
    expires_at: datetime
    prune_at: datetime


_APOSTROPHE_TRANSLATION = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u02bc": "'",
    "`": "'",
})
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100,
                 "D": 500, "M": 1000}
_RANK_TOKEN = r"(?P<rank>\d+|[IVXLCDM]+)"
_RANK_SUFFIXES = (
    re.compile(rf"\s*\+\s*{_RANK_TOKEN}\s*$", re.IGNORECASE),
    re.compile(
        rf"\s*\(\s*(?:(?:rank|rk)\.?\s*)?{_RANK_TOKEN}\s*\)\s*$",
        re.IGNORECASE),
    re.compile(
        rf"\s+(?:(?:rank|rk)\.?\s*)?{_RANK_TOKEN}\s*$", re.IGNORECASE),
)


def _name_key(value: str | None) -> str:
    text = (value or "").translate(_APOSTROPHE_TRANSLATION).casefold()
    # Apostrophes are optional in log text ("Kelins" and "Kelin's" match).
    text = text.replace("'", "")
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def _roman_to_int(token: str) -> int | None:
    upper = token.upper()
    if not upper or any(char not in _ROMAN_VALUES for char in upper):
        return None
    total = 0
    previous = 0
    for char in reversed(upper):
        value = _ROMAN_VALUES[char]
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    # Reject malformed strings such as IIII or IIX.  Ranks are small, but the
    # canonical check also makes suffix parsing predictable.
    if total <= 0 or _int_to_roman(total) != upper:
        return None
    return total


def _int_to_roman(value: int) -> str:
    pieces: list[str] = []
    remainder = value
    for amount, glyph in (
            (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
            (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
            (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while remainder >= amount:
            pieces.append(glyph)
            remainder -= amount
    return "".join(pieces)


def _parse_rank_token(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _roman_to_int(token)


def _split_rank(spell_name: str) -> tuple[str, int]:
    text = " ".join((spell_name or "").translate(
        _APOSTROPHE_TRANSLATION).strip().split())
    for pattern in _RANK_SUFFIXES:
        match = pattern.search(text)
        if not match:
            continue
        rank = _parse_rank_token(match.group("rank"))
        if rank is not None:
            return text[:match.start()].strip(), rank
    return text, 0


def split_spell_rank(spell_name: str) -> tuple[str, int]:
    """Return a normalized base spell name and its EQL upgrade rank."""

    return _split_rank(spell_name)


_SPELL_BY_KEY: dict[str, MezSpell] = {}
for _spell in MEZ_SPELLS:
    for _alias in (_spell.name, *_spell.aliases):
        _SPELL_BY_KEY[_name_key(_alias)] = _spell


def scaled_duration_ticks(base_ticks: int, rank: int = 0) -> int:
    """Apply EQL's 10%-per-rank scaling and round half-up to whole ticks."""

    if base_ticks <= 0:
        raise ValueError("base_ticks must be positive")
    if rank < 0:
        raise ValueError("rank cannot be negative")
    # Exact integer half-up form of floor(base * (1 + rank / 10) + 0.5).
    return (base_ticks * (10 + rank) + 5) // 10


def resolve_mez_spell(spell_name: str | None) -> ResolvedMezSpell | None:
    """Resolve a case/apostrophe-tolerant spell name and optional rank suffix."""

    if not spell_name:
        return None
    base_name, rank = _split_rank(spell_name)
    spell = _SPELL_BY_KEY.get(_name_key(base_name))
    if spell is None:
        return None
    ticks = scaled_duration_ticks(spell.base_ticks, rank)
    # Crowd-control spells use EQL's non-nuke cast track: four percent faster
    # per rank through rank ten.  Clamp later suffixes to the known tier-ten
    # floor rather than inventing a zero/negative cast time.
    cast_scale = 1.0 - 0.04 * min(10, max(0, rank))
    cast_seconds = spell.base_cast_seconds * cast_scale
    return ResolvedMezSpell(
        spell, rank, ticks, ticks * SERVER_TICK_SECONDS, cast_seconds)


def mez_urgency(remaining_seconds: float, *,
                warning_seconds: float = DEFAULT_WARNING_SECONDS,
                critical_seconds: float = DEFAULT_CRITICAL_SECONDS) -> str:
    """Return ``safe``, ``warning``, or ``critical`` for timer styling."""

    remaining = max(0.0, float(remaining_seconds))
    critical = max(0.0, float(critical_seconds))
    warning = max(critical, float(warning_seconds))
    if remaining <= critical:
        return "critical"
    if remaining <= warning:
        return "warning"
    return "safe"


def format_mez_remaining(remaining_seconds: float, *,
                         last_tick: bool = False) -> str:
    """Format a countdown without displaying zero before the actual expiry."""

    if last_tick:
        return "LAST TICK"
    seconds = max(0, ceil(float(remaining_seconds)))
    if remaining_seconds >= 60:
        minutes, remainder = divmod(seconds, 60)
        return f"{minutes}:{remainder:02d}"
    return f"{seconds}s"


class MezTracker:
    """Correlate local casts and landing lines into conservative mez timers."""

    def __init__(self, *, pending_seconds: float = 6.0,
                 area_landing_seconds: float = 1.25,
                 expiry_grace_seconds: float = 1.25) -> None:
        if pending_seconds <= 0:
            raise ValueError("pending_seconds must be positive")
        if area_landing_seconds <= 0:
            raise ValueError("area_landing_seconds must be positive")
        if expiry_grace_seconds < 0:
            raise ValueError("expiry_grace_seconds cannot be negative")
        self.pending_seconds = float(pending_seconds)
        self.area_landing_seconds = float(area_landing_seconds)
        self.expiry_grace_seconds = float(expiry_grace_seconds)
        self._pending: PendingMezCast | None = None
        self._nearby_pending: PendingMezCast | None = None
        self._skip_ambiguous_batch = False
        self._ignored_batch_at: datetime | None = None
        self._groups: dict[str, list[_ActiveMez]] = {}
        self._known_awake: dict[str, int] = {}
        self._recent_wake: dict[str, tuple[datetime, str]] = {}
        self._next_cast_id = 1
        self._next_timer_id = 1
        self._warned_timer_ids: set[int] = set()
        self._ambiguity_note = ""
        self._ambiguity_observed_at: datetime | None = None
        self._ambiguity_until: datetime | None = None
        self._ambiguity_count = 0

    @property
    def pending(self) -> PendingMezCast | None:
        return self._pending

    def begin_cast(self, spell_name: str, occurred_at: datetime) -> PendingMezCast | None:
        """Register a local cast, replacing any older correlation episode.

        Even an unrecognized own cast proves that a previous pending cast can
        no longer produce a legitimate late landing, so it safely cancels the
        older episode.
        """

        resolved = resolve_mez_spell(spell_name)
        if resolved is None:
            self._pending = None
            self._nearby_pending = None
            self._reset_landing_guard()
            return None
        nearby = self._nearby_pending
        # Landing prose does not identify the caster.  If a nearby player
        # started this same spell first and their result can still arrive,
        # quarantine that first whole-second batch.  A later batch (or an
        # explicit "resisted your" result) can then safely belong to us.  This
        # prevents simultaneous AE casts from doubling every tracked target.
        self._skip_ambiguous_batch = bool(
            nearby is not None
            and (nearby.resolved.spell.landing_family
                 == resolved.spell.landing_family)
            and nearby.began_at <= occurred_at
            and occurred_at <= self._base_pending_deadline(nearby)
        )
        self._ignored_batch_at = None
        self._nearby_pending = None
        pending = PendingMezCast(self._next_cast_id, resolved, occurred_at)
        self._next_cast_id += 1
        self._pending = pending
        return pending

    def observe_nearby_cast(self, spell_name: str,
                            occurred_at: datetime) -> bool:
        """Remember a compatible nearby cast without treating it as local."""

        resolved = resolve_mez_spell(spell_name)
        if resolved is None:
            return False
        pending = self._pending
        if (pending is not None
                and (pending.resolved.spell.landing_family
                     == resolved.spell.landing_family)):
            # Once a second caster enters the same actorless-result family,
            # any future success line is ambiguous.  Close only the local
            # correlation; already-confirmed timers remain valid.
            self._pending = None
            self._reset_landing_guard()
            self._mark_ambiguity(
                occurred_at,
                "Nearby same-family mez cast; unowned result ignored",
            )
        self._nearby_pending = PendingMezCast(
            0, resolved, occurred_at)
        return True

    def observe_unattributed_landing(self, occurred_at: datetime) -> None:
        """Close a nearby cast that resolved before our next local cast."""

        nearby = self._nearby_pending
        if nearby is not None and occurred_at >= nearby.began_at:
            self._nearby_pending = None

    def _reset_landing_guard(self) -> None:
        self._skip_ambiguous_batch = False
        self._ignored_batch_at = None

    def _mark_ambiguity(self, occurred_at: datetime, note: str) -> None:
        self._ambiguity_note = note
        self._ambiguity_observed_at = occurred_at
        self._ambiguity_until = occurred_at + timedelta(
            seconds=AMBIGUITY_NOTICE_SECONDS)
        self._ambiguity_count += 1

    def _base_pending_deadline(self, pending: PendingMezCast) -> datetime:
        correlation_seconds = max(
            MIN_CORRELATION_SECONDS,
            ceil(pending.resolved.cast_seconds) + CORRELATION_SLACK_SECONDS,
        )
        return pending.began_at + timedelta(
            seconds=min(self.pending_seconds, correlation_seconds))

    def _pending_deadline(self, pending: PendingMezCast) -> datetime:
        # Log timestamps have whole-second precision.  A spell-aware deadline
        # (ceil cast + one bounded second) accepts accelerated casts while
        # sharply reducing the chance that a nearby enchanter's later landing
        # is attributed to this player. ``pending_seconds`` remains a hard cap.
        deadline = self._base_pending_deadline(pending)
        if pending.first_landed_at is not None:
            area_deadline = pending.first_landed_at + timedelta(
                seconds=self.area_landing_seconds)
            deadline = min(deadline, area_deadline)
        return deadline

    def _current_pending(self, occurred_at: datetime) -> PendingMezCast | None:
        pending = self._pending
        if pending is not None and occurred_at > self._pending_deadline(pending):
            self._pending = None
            self._reset_landing_guard()
            return None
        return pending

    def cancel_pending(self, spell_name: str | None = None) -> bool:
        """Cancel a cast, optionally only when its spell identity matches."""

        pending = self._pending
        if pending is None:
            return False
        if spell_name:
            resolved = resolve_mez_spell(spell_name)
            if resolved is None or resolved.name != pending.resolved.name:
                return False
        self._pending = None
        self._reset_landing_guard()
        return True

    def observe_fizzle(self) -> bool:
        return self.cancel_pending()

    def observe_interrupt(self) -> bool:
        return self.cancel_pending()

    def observe_resist(self, spell_name: str | None = None,
                       occurred_at: datetime | None = None) -> bool:
        """Cancel a resisted single-target cast but retain an AE cast.

        One creature resisting an AE spell does not prove that the other
        landing lines will fail, so its pending correlation window stays open.
        The return value reports whether a pending cast was cancelled.
        """

        pending = self._pending
        if pending is None:
            return False
        if occurred_at is not None:
            pending = self._current_pending(occurred_at)
            if pending is None:
                return False
        if spell_name:
            resolved = resolve_mez_spell(spell_name)
            if resolved is None or resolved.name != pending.resolved.name:
                return False
        if pending.resolved.area:
            # This wording explicitly identifies our result, so any older
            # nearby caster's generic batch can no longer shadow our follow-up
            # AE landing lines.
            self._reset_landing_guard()
            return False
        self._pending = None
        self._reset_landing_guard()
        return True

    def observe_landing(self, target_name: str, occurred_at: datetime,
                        spell_name: str | None = None) -> MezRow | None:
        """Start/refresh a timer only when a pending local cast is confirmed."""

        display_target = " ".join((target_name or "").strip().split())
        if not display_target:
            return None
        pending = self._current_pending(occurred_at)
        if pending is None or occurred_at < pending.began_at:
            return None
        if spell_name:
            reported = resolve_mez_spell(spell_name)
            if reported is None or reported.name != pending.resolved.name:
                return None
        if self._skip_ambiguous_batch:
            if self._ignored_batch_at is None:
                self._ignored_batch_at = occurred_at
                self._mark_ambiguity(
                    occurred_at,
                    "Overlapping nearby mez cast; first result batch ignored",
                )
                return None
            if occurred_at <= self._ignored_batch_at:
                return None
            self._reset_landing_guard()

        key = _name_key(display_target)
        entries = self._groups.setdefault(key, [])
        # Recasts refresh existing same-name instances earliest-first.  Once
        # every old instance has been refreshed by this cast, another identical
        # landing line represents an additional indistinguishable creature.
        # If one indistinguishable instance is positively known awake, a new
        # successful landing accounts for that actor before it can be treated
        # as a refresh of an already-controlled twin.  This restores honest
        # group counts after re-mezzing a break.
        candidates = [] if self._known_awake.get(key, 0) > 0 else [
            entry for entry in entries if entry.cast_id != pending.cast_id]
        if candidates:
            active = min(candidates, key=lambda entry: entry.expires_at)
            self._warned_timer_ids.discard(active.timer_id)
            active.cast_id = pending.cast_id
            active.target_name = display_target
            active.resolved = pending.resolved
            active.landed_at = occurred_at
            # Current EQ Legends logs show the listed N-tick duration as the
            # guaranteed-safe interval, followed by one server-tick expiry
            # phase.  For example, a 36-second Mesmerization V landed at
            # 19:36:02 and naturally faded at 19:36:43.  Do not present that
            # phase as guaranteed time: switch to WAKE WINDOW at N*6 and keep
            # the row only through the conservative N*6..(N+1)*6 bound.
            active.safe_expires_at = occurred_at + timedelta(
                seconds=pending.resolved.duration_seconds)
            active.expires_at = active.safe_expires_at + timedelta(
                seconds=SERVER_TICK_SECONDS)
            active.prune_at = active.expires_at + timedelta(
                seconds=self.expiry_grace_seconds)
        else:
            safe_expires_at = occurred_at + timedelta(
                seconds=pending.resolved.duration_seconds)
            expires_at = safe_expires_at + timedelta(
                seconds=SERVER_TICK_SECONDS)
            active = _ActiveMez(
                timer_id=self._next_timer_id,
                cast_id=pending.cast_id,
                target_name=display_target,
                resolved=pending.resolved,
                landed_at=occurred_at,
                safe_expires_at=safe_expires_at,
                expires_at=expires_at,
                prune_at=expires_at + timedelta(
                    seconds=self.expiry_grace_seconds),
            )
            self._next_timer_id += 1
            entries.append(active)
            self._consume_known_awake(key)
            # This landing starts a new control episode for one instance of
            # the name; an earlier wake-chain dedupe must not suppress its
            # own immediate break/fade.
            self._recent_wake.pop(key, None)

        landed_count = pending.landed_count + 1
        first_landed_at = pending.first_landed_at or occurred_at
        if pending.resolved.area:
            self._pending = replace(
                pending, landed_count=landed_count,
                first_landed_at=first_landed_at)
        else:
            self._pending = None
            self._reset_landing_guard()
        return self._row_for_group(entries, occurred_at)

    def _prune(self, now: datetime) -> None:
        for key in list(self._groups):
            live: list[_ActiveMez] = []
            for entry in self._groups[key]:
                if entry.prune_at > now:
                    live.append(entry)
                else:
                    self._warned_timer_ids.discard(entry.timer_id)
                    self._mark_awake(key, now, "expiry")
            if live:
                self._groups[key] = live
            else:
                del self._groups[key]
        self._current_pending(now)

    def _mark_awake(self, key: str, occurred_at: datetime,
                    source: str) -> None:
        self._known_awake[key] = self._known_awake.get(key, 0) + 1
        self._recent_wake[key] = (occurred_at, source)

    def _consume_known_awake(self, key: str) -> bool:
        count = self._known_awake.get(key, 0)
        if count <= 0:
            return False
        if count == 1:
            del self._known_awake[key]
        else:
            self._known_awake[key] = count - 1
        return True

    def _pop_one(self, target_name: str,
                 occurred_at: datetime) -> _ActiveMez | None:
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
        """Remove one same-named timer when damage proves a mez broke."""

        key = _name_key(target_name)
        self._prune(occurred_at)
        # Once one indistinguishable actor of this name is known awake, its
        # fade -> awakened -> damage/attack chain must not consume the timers
        # for its still-controlled twins.  A later explicit fade can still
        # retire another member of the group.
        if self._known_awake.get(key, 0) > 0:
            return False
        removed = self._pop_one(target_name, occurred_at)
        if removed is None:
            return False
        self._mark_awake(key, occurred_at, "damage")
        return True

    def observe_kill(self, target_name: str, occurred_at: datetime) -> bool:
        """Remove one same-named timer when that visible actor dies."""

        key = _name_key(target_name)
        self._prune(occurred_at)
        # A known-awake instance dying accounts for the kill line; it is not
        # evidence that another same-named controlled instance also died.
        if self._consume_known_awake(key):
            return False
        return self._pop_one(target_name, occurred_at) is not None

    def _matching_candidate(
            self, target_name: str | None, occurred_at: datetime,
            spell_name: str | None = None,
    ) -> tuple[list[_ActiveMez], _ActiveMez, str] | None:
        resolved = resolve_mez_spell(spell_name) if spell_name else None
        if spell_name and resolved is None:
            return None
        self._prune(occurred_at)
        display_target = " ".join((target_name or "").strip().split())
        if display_target:
            key = _name_key(display_target)
            entries = self._groups.get(key)
            if not entries:
                return None
            candidates = entries
            if resolved is not None:
                candidates = [
                    entry for entry in entries
                    if entry.resolved.name == resolved.name
                ]
                if not candidates:
                    return None
            removed = min(candidates, key=lambda entry: entry.safe_expires_at)
            return entries, removed, key

        # Some clients omit the NPC from "Your <spell> spell has worn off."
        # The earliest matching timer is the only conservative choice.
        candidates = [
            entry
            for group in self._groups.values()
            for entry in group
            if resolved is None or entry.resolved.name == resolved.name
        ]
        if not candidates:
            return None
        removed = min(candidates, key=lambda entry: entry.safe_expires_at)
        key = _name_key(removed.target_name)
        return self._groups[key], removed, key

    def _discard_candidate(self, entries: list[_ActiveMez],
                           removed: _ActiveMez, key: str) -> None:
        entries.remove(removed)
        self._warned_timer_ids.discard(removed.timer_id)
        if not entries:
            del self._groups[key]

    def observe_fade(self, target_name: str | None, occurred_at: datetime,
                     spell_name: str | None = None) -> bool:
        """Remove one timer for a known mez fade (or a pre-validated fade)."""

        candidate = self._matching_candidate(
            target_name, occurred_at, spell_name)
        if candidate is None:
            return False
        entries, removed, key = candidate
        recent = self._recent_wake.get(key)
        if recent is not None:
            elapsed = (occurred_at - recent[0]).total_seconds()
            if (recent[1] != "fade"
                    and 0 <= elapsed <= WAKE_SIGNAL_DEDUPE_SECONDS):
                return False
        self._discard_candidate(entries, removed, key)
        self._mark_awake(key, occurred_at, "fade")
        return True

    def observe_overwrite(self, target_name: str | None,
                          occurred_at: datetime,
                          spell_name: str | None = None) -> bool:
        """Drop our timer when another caster takes ownership of the mez."""

        candidate = self._matching_candidate(
            target_name, occurred_at, spell_name)
        if candidate is None:
            return False
        self._discard_candidate(*candidate)
        return True

    def clear(self) -> int:
        """Clear pending/active state and return the number of active actors."""

        count = sum(len(entries) for entries in self._groups.values())
        self._pending = None
        self._nearby_pending = None
        self._reset_landing_guard()
        self._groups.clear()
        self._known_awake.clear()
        self._recent_wake.clear()
        self._warned_timer_ids.clear()
        self._ambiguity_note = ""
        self._ambiguity_observed_at = None
        self._ambiguity_until = None
        self._ambiguity_count = 0
        return count

    @staticmethod
    def _row_for_group(entries: Iterable[_ActiveMez], now: datetime,
                       warning_seconds: float = DEFAULT_WARNING_SECONDS,
                       critical_seconds: float = DEFAULT_CRITICAL_SECONDS) -> MezRow:
        grouped = tuple(entries)
        earliest = min(grouped, key=lambda entry: entry.safe_expires_at)
        safe_remaining = max(0.0, (
            earliest.safe_expires_at - now).total_seconds())
        remaining = max(0.0, (earliest.expires_at - now).total_seconds())
        last_tick = now >= earliest.safe_expires_at
        return MezRow(
            target_name=earliest.target_name,
            count=len(grouped),
            spell_name=earliest.resolved.name,
            rank=earliest.resolved.rank,
            landed_at=earliest.landed_at,
            safe_expires_at=earliest.safe_expires_at,
            expires_at=earliest.expires_at,
            duration_seconds=earliest.resolved.duration_seconds,
            safe_remaining_seconds=safe_remaining,
            remaining_seconds=remaining,
            last_tick=last_tick,
            urgency=mez_urgency(
                safe_remaining, warning_seconds=warning_seconds,
                critical_seconds=critical_seconds),
            ambiguity=(
                f"earliest expiry of {len(grouped)} same-name targets"
                if len(grouped) > 1 else ""
            ),
        )

    def snapshot(self, now: datetime, *, limit: int | None = 3,
                 warning_seconds: float = DEFAULT_WARNING_SECONDS,
                 critical_seconds: float = DEFAULT_CRITICAL_SECONDS) -> MezSnapshot:
        """Return earliest-expiring groups first, with a compact overflow count."""

        if limit is not None and limit < 0:
            raise ValueError("limit cannot be negative")
        self._prune(now)
        rows = [self._row_for_group(
            entries, now, warning_seconds, critical_seconds)
            for entries in self._groups.values()]
        rows.sort(key=lambda row: (
            row.safe_expires_at, row.target_name.casefold()))
        group_count = len(rows)
        visible = rows if limit is None else rows[:limit]
        hidden = 0 if limit is None else max(0, group_count - limit)
        ambiguity_note = self._ambiguity_note
        if (self._ambiguity_until is not None
                and now > self._ambiguity_until):
            ambiguity_note = ""
        return MezSnapshot(
            rows=tuple(visible), hidden_rows=hidden, group_count=group_count,
            active_count=sum(len(entries) for entries in self._groups.values()),
            ambiguity_note=ambiguity_note,
            ambiguity_count=self._ambiguity_count,
            ambiguity_observed_at=(
                self._ambiguity_observed_at if ambiguity_note else None),
            ambiguity_until=(self._ambiguity_until if ambiguity_note else None),
        )

    def pop_warning_events(self, now: datetime, *,
                           threshold_seconds: float = DEFAULT_WARNING_SECONDS,
                           enabled: bool = True) -> tuple[MezWarningEvent, ...]:
        """Emit each group's near-expiry warning once per timer/refresh cycle."""

        if not enabled or threshold_seconds <= 0:
            return ()
        self._prune(now)
        events: list[MezWarningEvent] = []
        for entries in self._groups.values():
            earliest = min(entries, key=lambda entry: entry.safe_expires_at)
            remaining = max(0.0, (
                earliest.safe_expires_at - now).total_seconds())
            if (remaining <= threshold_seconds and
                    earliest.timer_id not in self._warned_timer_ids):
                self._warned_timer_ids.add(earliest.timer_id)
                events.append(MezWarningEvent(
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
    "DEFAULT_CRITICAL_SECONDS",
    "DEFAULT_WARNING_SECONDS",
    "MEZ_SPELLS",
    "MezRow",
    "MezSnapshot",
    "MezSpell",
    "MezTracker",
    "MezWarningEvent",
    "PendingMezCast",
    "ResolvedMezSpell",
    "format_mez_remaining",
    "mez_urgency",
    "resolve_mez_spell",
    "scaled_duration_ticks",
    "split_spell_rank",
]
