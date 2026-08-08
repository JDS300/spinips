"""Immutable display snapshots shared by Python and the desktop preview."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ControlDisplayRow:
    control_kind: str
    timer_state: str
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
    confidence: str
    ambiguity: str


@dataclass(frozen=True)
class ControlDisplaySnapshot:
    rows: tuple[ControlDisplayRow, ...]
    hidden_rows: int
    group_count: int
    active_count: int
    notice_count: int
    ambiguity_count: int


def _active_row(row) -> ControlDisplayRow:
    return ControlDisplayRow(
        control_kind=str(getattr(row, "control_kind", "mez")),
        timer_state="active",
        target_name=row.target_name,
        count=row.count,
        spell_name=row.spell_name,
        rank=row.rank,
        landed_at=row.landed_at,
        safe_expires_at=row.safe_expires_at,
        expires_at=row.expires_at,
        duration_seconds=row.duration_seconds,
        safe_remaining_seconds=row.safe_remaining_seconds,
        remaining_seconds=row.remaining_seconds,
        last_tick=row.last_tick,
        urgency=row.urgency,
        confidence=str(getattr(row, "confidence", "confirmed")),
        ambiguity=str(getattr(row, "ambiguity", "")),
    )


def _notice_row(notice, *, control_kind: str) -> ControlDisplayRow:
    return ControlDisplayRow(
        control_kind=control_kind,
        timer_state=notice.status,
        target_name="RESULT NOT TRACKED",
        count=1,
        spell_name=notice.spell_name,
        rank=notice.rank,
        landed_at=notice.observed_at,
        safe_expires_at=notice.expires_at,
        expires_at=notice.expires_at,
        duration_seconds=0,
        safe_remaining_seconds=0.0,
        remaining_seconds=0.0,
        last_tick=False,
        urgency="critical" if notice.status == "failed" else "warning",
        confidence="unconfirmed",
        ambiguity=notice.detail,
    )


def merge_control_snapshots(mez_snapshot, lull_snapshot, *,
                            limit: int | None = 4,
                            include_mez: bool = True,
                            include_lull: bool = True) -> ControlDisplaySnapshot:
    """Merge independently tested trackers without mutating either snapshot."""

    if limit is not None and limit < 0:
        raise ValueError("limit cannot be negative")
    active = [
        *(_active_row(row) for row in mez_snapshot.rows if include_mez),
        *(_active_row(row) for row in lull_snapshot.rows if include_lull),
    ]
    active.sort(key=lambda row: (
        row.safe_expires_at, row.control_kind, row.target_name.casefold()))
    notices = ([_notice_row(notice, control_kind="lull")
                for notice in lull_snapshot.notices]
               if include_lull else [])
    ambiguity_note = (str(getattr(mez_snapshot, "ambiguity_note", ""))
                      if include_mez else "")
    if ambiguity_note:
        observed_at = (getattr(
            mez_snapshot, "ambiguity_observed_at", None) or datetime.min)
        expires_at = (getattr(
            mez_snapshot, "ambiguity_until", None) or observed_at)
        synthetic = type("MezAmbiguity", (), {
            "status": "ambiguous",
            "spell_name": "Mez",
            "rank": 0,
            "observed_at": observed_at,
            "expires_at": expires_at,
            "detail": ambiguity_note,
        })()
        notices.append(_notice_row(synthetic, control_kind="mez"))
    rows = [*active, *notices]
    visible = rows if limit is None else rows[:limit]
    hidden = 0 if limit is None else max(0, len(rows) - limit)
    ambiguity_count = (int(getattr(mez_snapshot, "ambiguity_count", 0))
                       if include_mez else 0)
    ambiguity_count += sum(
        1 for notice in lull_snapshot.notices
        if include_lull and notice.status == "ambiguous"
    )
    return ControlDisplaySnapshot(
        rows=tuple(visible),
        hidden_rows=hidden,
        group_count=(mez_snapshot.group_count if include_mez else 0)
        + (lull_snapshot.group_count if include_lull else 0),
        active_count=(mez_snapshot.active_count if include_mez else 0)
        + (lull_snapshot.active_count if include_lull else 0),
        notice_count=len(notices),
        ambiguity_count=ambiguity_count,
    )


__all__ = [
    "ControlDisplayRow",
    "ControlDisplaySnapshot",
    "merge_control_snapshots",
]
