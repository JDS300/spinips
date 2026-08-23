"""Tk-free debuff duration tracking for Loremaster.

Three families of debuff land on a mob and expire on a timer: damage over
time, attack-speed slows, and resist reductions.  They reach this module by
two different routes, which is why one tracker carries two paths.

A DoT names its target and its spell on every tick line, so attribution is
never in doubt and the tick doubles as a heartbeat: a DoT still ticking past
its computed expiry has been extended by a focus item, and the row is held
open rather than dropped.

Slow and resist print only prose -- "a froglok tad yawns." -- which names the
target but not the spell, and which is equally visible when somebody else
casts.  Those follow the mez model: a landing is accepted only while a
compatible local cast is pending, and the pending cast supplies the duration.
Four slows share the "yawns" line and their durations differ by twenty ticks,
so that correlation is what makes the countdown correct rather than plausible.

Durations are computed from caster level and upgrade rank.  They do not model
focus items, which no part of Loremaster can see, so slow and resist rows
report ``duration_confidence == "conservative"``.

Spell data is scraped from Allakhazam by ``tools/scrape_debuff_spells.py`` into
``tests/fixtures/debuff_spell_reference.json``.  Every row keeps the published
endpoints it was derived from, and the test suite asserts each formula still
reproduces them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from mez_timer import (
    DEFAULT_CRITICAL_SECONDS,
    DEFAULT_WARNING_SECONDS,
    SERVER_TICK_SECONDS,
    scaled_duration_ticks,
    split_spell_rank,
)


# A DoT is held open this long past its last tick before it is presumed gone.
DOT_HEARTBEAT_GRACE_TICKS = 2
# How long a begin-cast stays eligible to claim a landing line.
PENDING_SECONDS = 12.0
# A conservative row lingers briefly at zero instead of vanishing, because the
# countdown is an estimate and a focused debuff outlives it.
EXPIRY_GRACE_SECONDS = 6.0
DEFAULT_MOB_LIMIT = 6


@dataclass(frozen=True)
class DebuffSpell:
    """A debuff whose duration is derived from published level endpoints."""

    name: str
    kind: str                      # "dot" | "slow" | "resist"
    duration_formula: str | None   # None means the duration is fixed
    duration_cap_ticks: int        # the cap, or the fixed duration itself
    landing_family: str | None     # None for DoTs, which self-attribute
    published_endpoints: tuple[tuple[int, int], ...] = ()
    aliases: tuple[str, ...] = ()


def _half_up(numerator: int, denominator: int) -> int:
    """Integer round-half-up, avoiding float rounding surprises."""

    return (numerator * 2 + denominator) // (2 * denominator)


DURATION_FORMULAS = {
    "level_half_roundup": lambda level: _half_up(level, 2),
    "level_half_plus1": lambda level: level // 2 + 1,
    "level": lambda level: level,
    "level_x30": lambda level: level * 30,
    "level_x2_plus10": lambda level: level * 2 + 10,
    "level_x3_plus10": lambda level: level * 3 + 10,
}


DEBUFF_SPELLS: tuple[DebuffSpell, ...] = (
    # --- slow - attack speed reduction ---------------------------
    DebuffSpell("Drowsy", "slow", "level_half_roundup", 35, "yawns", ((5, 3), (70, 35))),
    DebuffSpell("Forlorn Deeds", "slow", "level_half_roundup", 35, "slows_down", ((57, 29), (70, 35))),
    DebuffSpell("Languid Pace", "slow", "level_half_roundup", 35, "slows_down", ((9, 5), (70, 35))),
    DebuffSpell("Plague of Insects", "slow", "level_half_roundup", 35, "plague_insects", ((54, 27), (70, 35))),
    DebuffSpell("Sha's Advantage", "slow", "level_half_roundup", 35, "fighting_edge", ((60, 30), (70, 35))),
    DebuffSpell("Sha's Lethargy", "slow", "level_half_roundup", 35, "lethargic", ((50, 25), (70, 35))),
    DebuffSpell("Shiftless Deeds", "slow", "level_half_roundup", 35, "slows_down", ((41, 21), (70, 35))),
    DebuffSpell("Tagar's Insects", "slow", "level_half_roundup", 35, "yawns", ((27, 14), (70, 35))),
    DebuffSpell("Tepid Deeds", "slow", "level_half_roundup", 35, "slows_down", ((23, 12), (70, 35))),
    DebuffSpell("Tigir's Insects", "slow", "level_half_roundup", 35, "yawns", ((58, 29), (70, 35))),
    DebuffSpell("Togor's Insects", "slow", "level_half_roundup", 35, "yawns", ((38, 19), (70, 35))),
    DebuffSpell("Turgur's Insects", "slow", "level", 65, "yawns", ((51, 51), (65, 65))),
    DebuffSpell("Walking Sleep", "slow", "level_half_roundup", 35, "yawns", ((13, 7), (70, 35))),
    # --- resist debuffs ------------------------------------------
    DebuffSpell("Glamour of Tunare", "resist", "level_x3_plus10", 205, "tunarian", ((53, 169), (65, 205))),
    DebuffSpell("Insidious Decay", "resist", "level_x2_plus10", 140, "feverish", ((52, 114), (65, 140))),
    DebuffSpell("Malaise", "resist", "level_x2_plus10", 140, "malaise", ((18, 46), (65, 140))),
    DebuffSpell("Malaisement", "resist", "level_x2_plus10", 140, "malaisement", ((32, 74), (65, 140))),
    DebuffSpell("Malo", "resist", "level_x2_plus10", 140, "malosi", ((60, 130), (65, 140))),
    DebuffSpell("Malosi", "resist", "level_x2_plus10", 140, "malosi", ((48, 106), (65, 140))),
    DebuffSpell("Malosini", "resist", "level_x3_plus10", 205, "malosi", ((57, 181), (65, 205))),
    DebuffSpell("Ro's Smoldering Disjunction", "resist", None, 100, "cold_flame", ()),
    DebuffSpell("Scent of Terris", "resist", "level_x2_plus10", 140, "dark_haze", ((52, 114), (65, 140))),
    DebuffSpell("Tashan", "resist", "level", 60, "tashan", ()),
    DebuffSpell("Tashani", "resist", "level_x2_plus10", 140, "tashan", ((18, 46), (65, 140))),
    DebuffSpell("Tashania", "resist", "level_x2_plus10", 140, "tashan", ((41, 92), (65, 140))),
    DebuffSpell("Tashanian", "resist", "level_x2_plus10", 140, "tashan", ((57, 124), (65, 140))),
    DebuffSpell("Tashina", "resist", "level_x2_plus10", 140, "tashan", ((2, 14), (65, 140))),
    DebuffSpell("Wind of Tashani", "resist", "level_x2_plus10", 140, "tashan", ((55, 120), (65, 140))),
    DebuffSpell("Wind of Tashanian", "resist", "level_x2_plus10", 140, "tashan", ((60, 130), (65, 140))),
    # --- damage over time ----------------------------------------
    DebuffSpell("Affliction", "dot", None, 14, None, ()),
    DebuffSpell("Anathema", "dot", None, 5, None, ()),
    DebuffSpell("Ancient Scourge of Nife", "dot", None, 7, None, ()),
    DebuffSpell("Asphyxiate", "dot", None, 8, None, ()),
    DebuffSpell("Asystole", "dot", None, 7, None, ()),
    DebuffSpell("Bane of Nife", "dot", None, 7, None, ()),
    DebuffSpell("Boil Blood", "dot", None, 7, None, ()),
    DebuffSpell("Breath of Ro", "dot", None, 9, None, ()),
    DebuffSpell("Cancelling of Life", "dot", None, 10, None, ()),
    DebuffSpell("Cascading Darkness", "dot", None, 16, None, ()),
    DebuffSpell("Cessation of Cor", "dot", None, 9, None, ()),
    DebuffSpell("Cessation of Life", "dot", None, 16, None, ()),
    DebuffSpell("Chilling Embrace", "dot", None, 6, None, ()),
    DebuffSpell("Choke", "dot", "level_half_roundup", 8, None, ((11, 6), (16, 8))),
    DebuffSpell("Clinging Darkness", "dot", "level_half_roundup", 8, None, ((4, 2), (16, 8))),
    DebuffSpell("Creeping Crud", "dot", None, 8, None, ()),
    DebuffSpell("Dark Soul", "dot", None, 5, None, ()),
    DebuffSpell("Devouring Darkness", "dot", None, 13, None, ()),
    DebuffSpell("Disease Cloud", "dot", "level_x30", 60, None, ((1, 30), (2, 60))),
    DebuffSpell("Dooming Darkness", "dot", "level_half_roundup", 15, None, ((27, 14), (30, 15))),
    DebuffSpell("Drifting Death", "dot", None, 9, None, ()),
    DebuffSpell("Drones of Doom", "dot", None, 8, None, ()),
    DebuffSpell("Engulfing Darkness", "dot", None, 10, None, ()),
    DebuffSpell("Envenomed Bolt", "dot", None, 6, None, ()),
    DebuffSpell("Envenomed Breath", "dot", None, 7, None, ()),
    DebuffSpell("Eternities Torment", "dot", None, 21, None, ()),
    DebuffSpell("Flame Lick", "dot", "level_half_plus1", 6, None, ((1, 1), (10, 6))),
    DebuffSpell("Funeral Pyre of Kelador", "dot", None, 8, None, ()),
    DebuffSpell("Gasping Embrace", "dot", None, 8, None, ()),
    DebuffSpell("Heart Flutter", "dot", None, 6, None, ()),
    DebuffSpell("Heat Blood", "dot", None, 6, None, ()),
    DebuffSpell("Ignite Blood", "dot", None, 7, None, ()),
    DebuffSpell("Immolate", "dot", None, 8, None, ()),
    DebuffSpell("Imprecation", "dot", None, 5, None, ()),
    DebuffSpell("Infectious Cloud", "dot", None, 21, None, ()),
    DebuffSpell("Insidious Fever", "dot", "level_x2_plus10", 140, None, ((17, 44), (65, 140))),
    DebuffSpell("Insidious Malady", "dot", "level_x2_plus10", 140, None, ((38, 86), (65, 140))),
    DebuffSpell("Leech", "dot", None, 9, None, ()),
    DebuffSpell("Negation of Life", "dot", None, 15, None, ()),
    DebuffSpell("Plague", "dot", None, 13, None, ()),
    DebuffSpell("Poison Bolt", "dot", "level_half_plus1", 4, None, ((4, 3), (7, 4))),
    DebuffSpell("Pox of Bertoxxulous", "dot", None, 14, None, ()),
    DebuffSpell("Pyrocruor", "dot", None, 8, None, ()),
    DebuffSpell("Scourge", "dot", None, 12, None, ()),
    DebuffSpell("Shallow Breath", "dot", None, 2, None, ()),
    DebuffSpell("Sicken", "dot", None, 14, None, ()),
    DebuffSpell("Stinging Swarm", "dot", "level_half_roundup", 9, None, ((10, 5), (18, 9))),
    DebuffSpell("Suffocate", "dot", None, 8, None, ()),
    DebuffSpell("Suffocating Sphere", "dot", None, 7, None, ()),
    DebuffSpell("Tainted Breath", "dot", None, 7, None, ()),
    DebuffSpell("Torment of Argli", "dot", None, 20, None, ()),
    DebuffSpell("Vengeance of Nature", "dot", None, 5, None, ()),
    DebuffSpell("Venom of the Snake", "dot", None, 6, None, ()),
    DebuffSpell("Vexing Mordinia", "dot", None, 9, None, ()),
    DebuffSpell("Winged Death", "dot", None, 9, None, ()),
    DebuffSpell("Zevfeer's Theft of Vitae", "dot", None, 9, None, ()),
)


DEBUFF_LANDING_COMPATIBILITY: dict[str, frozenset[str]] = {
    "cold_flame": frozenset(["Ro's Smoldering Disjunction"]),
    "dark_haze": frozenset(['Scent of Terris']),
    "feverish": frozenset(['Insidious Decay']),
    "fighting_edge": frozenset(["Sha's Advantage"]),
    "lethargic": frozenset(["Sha's Lethargy"]),
    "malaise": frozenset(['Malaise']),
    "malaisement": frozenset(['Malaisement']),
    "malosi": frozenset(['Malo', 'Malosi', 'Malosini']),
    "plague_insects": frozenset(['Plague of Insects']),
    "slows_down": frozenset(['Forlorn Deeds', 'Languid Pace', 'Shiftless Deeds', 'Tepid Deeds']),
    "tashan": frozenset(['Tashan', 'Tashani', 'Tashania', 'Tashanian', 'Tashina', 'Wind of Tashani', 'Wind of Tashanian']),
    "tunarian": frozenset(['Glamour of Tunare']),
    "yawns": frozenset(['Drowsy', "Tagar's Insects", "Tigir's Insects", "Togor's Insects", "Turgur's Insects", 'Walking Sleep']),
}


_APOSTROPHE_TRANSLATION = str.maketrans({
    "‘": "'", "’": "'", "ʼ": "'", "`": "'",
})


def _name_key(value: str | None) -> str:
    """Case- and apostrophe-tolerant lookup key, matching mez_timer."""

    text = " ".join((value or "").translate(
        _APOSTROPHE_TRANSLATION).strip().split())
    return text.casefold().replace("'", "")


_SPELL_BY_KEY: dict[str, DebuffSpell] = {}
for _spell in DEBUFF_SPELLS:
    for _alias in (_spell.name, *_spell.aliases):
        _SPELL_BY_KEY[_name_key(_alias)] = _spell


def duration_ticks(spell: DebuffSpell, caster_level: int, rank: int = 0) -> int:
    """Ticks for a spell at a caster level and upgrade rank.

    The published cap is a *level* cap, so it clamps the level-derived base.
    Rank scaling then applies on top and may legitimately exceed it.
    """

    if spell.duration_formula is None:
        base = spell.duration_cap_ticks
    else:
        formula = DURATION_FORMULAS[spell.duration_formula]
        base = min(formula(max(1, caster_level)), spell.duration_cap_ticks)
    base = max(1, base)
    return scaled_duration_ticks(base, rank) if rank else base


@dataclass(frozen=True)
class ResolvedDebuff:
    """A named debuff resolved to a concrete duration."""

    spell: DebuffSpell
    rank: int
    caster_level: int
    duration_ticks: int

    @property
    def name(self) -> str:
        return self.spell.name

    @property
    def kind(self) -> str:
        return self.spell.kind

    @property
    def duration_seconds(self) -> int:
        return self.duration_ticks * SERVER_TICK_SECONDS

    @property
    def duration_confidence(self) -> str:
        """DoTs are confirmed by their ticks; the rest are estimates.

        Nothing in Loremaster can see focus items, which extend duration, so a
        computed countdown for a slow or resist debuff is a floor rather than a
        measurement.
        """

        return "exact" if self.spell.kind == "dot" else "conservative"


def resolve_debuff_spell(spell_name: str | None,
                         caster_level: int = 1) -> ResolvedDebuff | None:
    """Resolve a log spell name, tolerating case, apostrophes and rank suffix."""

    if not spell_name:
        return None
    base_name, rank = split_spell_rank(spell_name)
    spell = _SPELL_BY_KEY.get(_name_key(base_name))
    if spell is None:
        return None
    return ResolvedDebuff(spell, rank, caster_level,
                          duration_ticks(spell, caster_level, rank))


def debuff_urgency(remaining_seconds: float, *,
                   warning_seconds: float = DEFAULT_WARNING_SECONDS,
                   critical_seconds: float = DEFAULT_CRITICAL_SECONDS) -> str:
    if remaining_seconds <= critical_seconds:
        return "critical"
    if remaining_seconds <= warning_seconds:
        return "warning"
    return "safe"


def format_debuff_remaining(remaining_seconds: float) -> str:
    seconds = max(0, int(remaining_seconds))
    if seconds >= 60:
        return f"{seconds // 60}:{seconds % 60:02d}"
    return f"{seconds}s"


@dataclass(frozen=True)
class PendingDebuffCast:
    """A local begin-cast still eligible to claim a landing or a first tick."""

    resolved: ResolvedDebuff
    cast_at: datetime


@dataclass(frozen=True)
class DebuffRow:
    """One debuff counting down on one mob."""

    target: str
    spell: str
    kind: str
    rank: int
    expires_at: datetime
    remaining_seconds: float
    urgency: str
    duration_confidence: str
    last_tick_at: datetime | None
    expired: bool


@dataclass(frozen=True)
class DebuffGroup:
    """Every tracked debuff on a single mob."""

    target: str
    rows: tuple[DebuffRow, ...]

    @property
    def urgency(self) -> str:
        for level in ("critical", "warning", "safe"):
            if any(row.urgency == level for row in self.rows):
                return level
        return "safe"


@dataclass(frozen=True)
class DebuffSnapshot:
    groups: tuple[DebuffGroup, ...] = ()
    overflow: int = 0

    @property
    def active_count(self) -> int:
        return sum(len(group.rows) for group in self.groups)


@dataclass
class _ActiveDebuff:
    resolved: ResolvedDebuff
    target: str            # as first seen, for display
    landed_at: datetime
    expires_at: datetime
    last_tick_at: datetime | None = None


class DebuffTracker:
    """Correlates local casts with landings and tick lines into live timers."""

    def __init__(self, *, pending_seconds: float = PENDING_SECONDS) -> None:
        self._pending_seconds = pending_seconds
        self._pending: list[PendingDebuffCast] = []
        self._active: dict[tuple[str, str], _ActiveDebuff] = {}
        self._caster_level = 1

    # -- level ---------------------------------------------------------
    def set_caster_level(self, level: int) -> None:
        if level and level > 0:
            self._caster_level = int(level)

    @property
    def caster_level(self) -> int:
        return self._caster_level

    # -- casts ---------------------------------------------------------
    def _prune_pending(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self._pending_seconds)
        self._pending = [p for p in self._pending if p.cast_at >= cutoff]

    def begin_cast(self, spell_name: str, occurred_at: datetime,
                   caster_level: int | None = None) -> bool:
        """Record a local begin-cast. Returns True when the spell is tracked."""

        if caster_level:
            self.set_caster_level(caster_level)
        resolved = resolve_debuff_spell(spell_name, self._caster_level)
        if resolved is None:
            return False
        self._prune_pending(occurred_at)
        self._pending.append(PendingDebuffCast(resolved, occurred_at))
        return True

    def observe_nearby_cast(self, spell_name: str,
                            occurred_at: datetime) -> None:
        """Somebody else cast. Deliberately does not arm the tracker.

        Their landing line looks exactly like ours, so accepting it would put
        another player's slow on our deck with our duration.
        """

        self._prune_pending(occurred_at)

    def cancel_pending(self, spell_name: str | None,
                       occurred_at: datetime) -> bool:
        """Drop a pending cast after a fizzle, interrupt or resist."""

        self._prune_pending(occurred_at)
        if not self._pending:
            return False
        if not spell_name:
            self._pending.pop()
            return True
        key = _name_key(split_spell_rank(spell_name)[0])
        for index in range(len(self._pending) - 1, -1, -1):
            if _name_key(self._pending[index].resolved.name) == key:
                self._pending.pop(index)
                return True
        return False

    def observe_resist(self, spell_name: str | None,
                       occurred_at: datetime) -> bool:
        return self.cancel_pending(spell_name, occurred_at)

    def observe_fizzle(self, spell_name: str | None,
                       occurred_at: datetime) -> bool:
        return self.cancel_pending(spell_name, occurred_at)

    def observe_interrupt(self, spell_name: str | None,
                          occurred_at: datetime) -> bool:
        return self.cancel_pending(spell_name, occurred_at)

    # -- landings ------------------------------------------------------
    def _take_pending(self, occurred_at: datetime, *,
                      family: str | None = None,
                      spell_name: str | None = None,
                      ) -> PendingDebuffCast | None:
        """Claim the newest pending cast matching a family or an exact name."""

        self._prune_pending(occurred_at)
        candidates = DEBUFF_LANDING_COMPATIBILITY.get(family or "", frozenset())
        wanted = _name_key(split_spell_rank(spell_name)[0]) if spell_name else None
        for index in range(len(self._pending) - 1, -1, -1):
            pending = self._pending[index]
            if pending.cast_at > occurred_at:
                continue
            if wanted is not None:
                if _name_key(pending.resolved.name) != wanted:
                    continue
            elif pending.resolved.name not in candidates:
                continue
            return self._pending.pop(index)
        return None

    def _arm(self, target_name: str, resolved: ResolvedDebuff,
             occurred_at: datetime, *, tick_at: datetime | None = None) -> None:
        key = (_name_key(target_name), resolved.name)
        # EQ capitalises the first word of a line, so the same mob arrives as
        # "An abhorrent" in a landing and "an abhorrent" in a kill. Key on the
        # folded name -- mez_timer has always done this -- and keep whichever
        # spelling was seen first for the deck to display.
        display = self._active[key].target if key in self._active else target_name
        self._active[key] = _ActiveDebuff(
            resolved=resolved,
            target=display,
            landed_at=occurred_at,
            expires_at=occurred_at + timedelta(seconds=resolved.duration_seconds),
            last_tick_at=tick_at)

    def observe_landing(self, target_name: str, family: str,
                        occurred_at: datetime) -> bool:
        """A slow or resist landing line. Only counts if we cast it."""

        if not target_name:
            return False
        pending = self._take_pending(occurred_at, family=family)
        if pending is None:
            return False
        self._arm(target_name, pending.resolved, occurred_at)
        return True

    def observe_dot_tick(self, target_name: str, spell_name: str,
                         occurred_at: datetime) -> bool:
        """A DoT damage line, which names both target and spell."""

        if not target_name:
            return False
        resolved = resolve_debuff_spell(spell_name, self._caster_level)
        if resolved is None or resolved.kind != "dot":
            return False
        key = (_name_key(target_name), resolved.name)
        pending = self._take_pending(occurred_at, spell_name=resolved.name)
        active = self._active.get(key)
        if pending is not None:
            # Count from the cast, not from the first tick we happened to see.
            self._arm(target_name, pending.resolved, pending.cast_at,
                      tick_at=occurred_at)
            return True
        if active is not None:
            active.last_tick_at = occurred_at
            return True
        # Ticking with no pending cast: we started reading the log mid-fight.
        self._arm(target_name, resolved, occurred_at, tick_at=occurred_at)
        return True

    # -- endings -------------------------------------------------------
    def observe_fade(self, target_name: str | None, spell_name: str | None,
                     occurred_at: datetime) -> bool:
        resolved = resolve_debuff_spell(spell_name, self._caster_level)
        if resolved is None:
            return False
        if target_name:
            return self._active.pop(
                (_name_key(target_name), resolved.name), None) is not None
        # A fade line without a target clears that spell everywhere.
        doomed = [k for k in self._active if k[1] == resolved.name]
        for key in doomed:
            del self._active[key]
        return bool(doomed)

    def observe_overwrite(self, target_name: str | None,
                          spell_name: str | None,
                          occurred_at: datetime) -> bool:
        return self.observe_fade(target_name, spell_name, occurred_at)

    def observe_kill(self, target_name: str, occurred_at: datetime) -> bool:
        folded = _name_key(target_name)
        doomed = [k for k in self._active if k[0] == folded]
        for key in doomed:
            del self._active[key]
        return bool(doomed)

    def clear(self) -> int:
        cleared = len(self._active)
        self._active.clear()
        self._pending.clear()
        return cleared

    # -- snapshot ------------------------------------------------------
    def _row(self, active: _ActiveDebuff, now: datetime, *,
             warning_seconds: float, critical_seconds: float) -> DebuffRow:
        remaining = (active.expires_at - now).total_seconds()
        return DebuffRow(
            target=active.target,
            spell=active.resolved.name,
            kind=active.resolved.kind,
            rank=active.resolved.rank,
            expires_at=active.expires_at,
            remaining_seconds=max(0.0, remaining),
            urgency=debuff_urgency(remaining, warning_seconds=warning_seconds,
                                   critical_seconds=critical_seconds),
            duration_confidence=active.resolved.duration_confidence,
            last_tick_at=active.last_tick_at,
            expired=remaining <= 0.0)

    def _retain(self, active: _ActiveDebuff, now: datetime) -> bool:
        """Should this row stay on the deck?"""

        if now <= active.expires_at:
            return True
        if active.resolved.kind == "dot":
            # The heartbeat is ground truth: a DoT still ticking past its
            # estimate has been extended by a focus item.
            if active.last_tick_at is None:
                return False
            grace = DOT_HEARTBEAT_GRACE_TICKS * SERVER_TICK_SECONDS
            return (now - active.last_tick_at).total_seconds() <= grace
        # A conservative countdown lingers briefly rather than vanishing.
        return (now - active.expires_at).total_seconds() <= EXPIRY_GRACE_SECONDS

    def snapshot(self, now: datetime, *, limit: int | None = DEFAULT_MOB_LIMIT,
                 warning_seconds: float = DEFAULT_WARNING_SECONDS,
                 critical_seconds: float = DEFAULT_CRITICAL_SECONDS,
                 kinds: frozenset[str] | None = None) -> DebuffSnapshot:
        for key in [k for k, a in self._active.items() if not self._retain(a, now)]:
            del self._active[key]

        grouped: dict[str, list[DebuffRow]] = {}
        for active in self._active.values():
            if kinds is not None and active.resolved.kind not in kinds:
                continue
            grouped.setdefault(active.target, []).append(
                self._row(active, now, warning_seconds=warning_seconds,
                          critical_seconds=critical_seconds))
        if not grouped:
            return DebuffSnapshot()

        groups = [
            DebuffGroup(target=target,
                        rows=tuple(sorted(rows, key=lambda r: (r.remaining_seconds,
                                                               r.spell))))
            for target, rows in grouped.items()
        ]
        groups.sort(key=lambda g: (min(r.remaining_seconds for r in g.rows), g.target))

        overflow = 0
        if limit is not None and len(groups) > limit:
            overflow = len(groups) - limit
            groups = groups[:limit]
        return DebuffSnapshot(groups=tuple(groups), overflow=overflow)


__all__ = [
    "DEBUFF_LANDING_COMPATIBILITY",
    "DEBUFF_SPELLS",
    "DURATION_FORMULAS",
    "DebuffGroup",
    "DebuffRow",
    "DebuffSnapshot",
    "DebuffSpell",
    "DebuffTracker",
    "PendingDebuffCast",
    "ResolvedDebuff",
    "debuff_urgency",
    "duration_ticks",
    "format_debuff_remaining",
    "resolve_debuff_spell",
]
