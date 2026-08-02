"""Pure ownership state for reliable charmed-pet break notifications.

EverQuest's text log does not expose actor IDs, so a creature merely dying,
zoning, or being replaced by a new charm is not proof that charm *broke*.
This helper deliberately emits only for a recognized charm-fade line while a
matching charm claim is active.  All other lifecycle transitions are silent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _identity(name: str | None) -> str:
    return (name or "").strip().casefold()


@dataclass(frozen=True)
class ActiveCharm:
    """The one creature the local player currently controls through charm."""

    pet_name: str
    claimed_at: datetime
    charm_spell: str = ""


@dataclass(frozen=True)
class CharmBreakEvent:
    """A log-proven transition from an active charm to no active charm."""

    event_id: int
    pet_name: str
    charm_spell: str
    occurred_at: datetime


class CharmBreakDetector:
    """Track one active charm and emit each proven break exactly once.

    ``claim`` silently replaces a previous creature because landing another
    charm is an intentional ownership transition, not a break alert.  Call
    ``clear_silently`` for death, zone, session-reset, and confirmed pet-death
    cleanup.  ``observe_fade`` is the sole event-producing transition.
    """

    def __init__(self) -> None:
        self._active: ActiveCharm | None = None
        self._next_event_id = 1

    @property
    def active(self) -> ActiveCharm | None:
        return self._active

    def claim(self, pet_name: str, claimed_at: datetime,
              charm_spell: str = "") -> ActiveCharm:
        display_name = (pet_name or "").strip()
        if not display_name:
            raise ValueError("a charm claim requires a pet name")

        current = self._active
        if current is not None and _identity(current.pet_name) == _identity(display_name):
            # Owner-only pet chatter can repeat during one charm.  Preserve the
            # original claim time and any spell identity already learned.
            spell = (charm_spell or current.charm_spell).strip()
            self._active = ActiveCharm(current.pet_name, current.claimed_at, spell)
        else:
            self._active = ActiveCharm(
                display_name, claimed_at, (charm_spell or "").strip())
        return self._active

    def clear_silently(self, pet_name: str | None = None) -> ActiveCharm | None:
        """Forget ownership without producing a break event.

        When ``pet_name`` is supplied, a different active creature is left
        untouched.  This makes death cleanup safe in a busy combat log.
        """
        current = self._active
        if current is None:
            return None
        if pet_name and _identity(pet_name) != _identity(current.pet_name):
            return None
        self._active = None
        return current

    def observe_fade(self, *, spell_name: str, occurred_at: datetime,
                     target_name: str | None = None,
                     is_charm_spell: bool) -> CharmBreakEvent | None:
        """Return one event when this fade proves the active charm ended.

        Targetless fade lines are accepted because EQ permits one controlled
        charm at a time.  Named fades must match the active creature.  Once an
        event is returned the claim is cleared, so duplicate log lines cannot
        emit the same break twice.
        """
        current = self._active
        if current is None or not is_charm_spell:
            return None
        if target_name and _identity(target_name) != _identity(current.pet_name):
            return None

        event = CharmBreakEvent(
            event_id=self._next_event_id,
            pet_name=current.pet_name,
            charm_spell=(spell_name or current.charm_spell).strip(),
            occurred_at=occurred_at,
        )
        self._next_event_id += 1
        self._active = None
        return event


__all__ = ["ActiveCharm", "CharmBreakDetector", "CharmBreakEvent"]
