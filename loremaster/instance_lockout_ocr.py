"""Conservative OCR parsing for EverQuest's Alt+Z lockout table.

The game does not write Outstanding Instance Timers to the text log.  This
module turns a frozen, user-requested screen capture into reviewable D0-D4 raid
lockouts without reading process memory or injecting into EverQuest.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Iterable

from hover_ocr import OcrLine
from weekly_tracker import RAID_TARGETS, normalize_target


_TIMER_RE = re.compile(
    r"(?P<days>[0-9Oo]{1,3})\s*d\s*[-:;.,|]?\s*"
    r"(?P<hours>[0-9Oo]{1,2})\s*h\s*[-:;.,|]?\s*"
    r"(?P<minutes>[0-9Oo]{1,2})\s*m\s*[-:;.,|]?\s*"
    r"(?P<seconds>[0-9Oo]{1,2})\s*s\b", re.I)
_DIFFICULTY_RE = re.compile(r"\b(?:solo|group)\s*([0-4])\b", re.I)
_VARIANT_RE = re.compile(
    r"^[\s([{<]*(?:adaptive|normal|fused|refined)[\s)\]}>:;-]*", re.I)


@dataclass(frozen=True, slots=True)
class ParsedRaidLockout:
    target: str
    difficulty: int
    remaining_seconds: int
    instance_name: str
    event_name: str
    raw_text: str


def _number(value: str) -> int:
    return int(value.replace("O", "0").replace("o", "0"))


def _row_groups(lines: Iterable[OcrLine]) -> list[list[OcrLine]]:
    useful = [line for line in lines if line.text.strip()]
    useful.sort(key=lambda line: (line.y + line.height / 2.0, line.x))
    groups: list[list[OcrLine]] = []
    centers: list[float] = []
    for line in useful:
        center = line.y + line.height / 2.0
        if groups:
            tolerance = max(7.0, line.height * 0.72)
            if abs(center - centers[-1]) <= tolerance:
                groups[-1].append(line)
                count = len(groups[-1])
                centers[-1] = ((centers[-1] * (count - 1)) + center) / count
                continue
        groups.append([line])
        centers.append(center)
    return groups


def _ocr_name(value: str) -> str:
    value = value.replace("|", " ").replace("—", "-").replace("–", "-")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _target_from_event(value: str) -> str:
    candidate = _ocr_name(value)
    if not candidate:
        return ""
    direct: dict[str, str] = {}
    for target in RAID_TARGETS:
        direct[_ocr_name(target.name)] = target.name
        for alias in target.aliases:
            direct[_ocr_name(alias)] = target.name
    if candidate in direct:
        return direct[candidate]

    # A merged OCR line may retain the variant before the event. Prefer an
    # explicit canonical name contained in that suffix before fuzzy matching.
    for target in sorted(RAID_TARGETS, key=lambda item: len(item.name), reverse=True):
        canonical = _ocr_name(target.name)
        if re.search(rf"(?:^|\s){re.escape(canonical)}(?:$|\s)", candidate):
            return target.name

    best_name = ""
    best_ratio = 0.0
    for target in RAID_TARGETS:
        canonical = _ocr_name(target.name)
        ratio = SequenceMatcher(None, candidate, canonical).ratio()
        if ratio > best_ratio:
            best_name, best_ratio = target.name, ratio
    return best_name if best_ratio >= 0.84 else ""


def _parse_row(parts: list[OcrLine]) -> ParsedRaidLockout | None:
    ordered = sorted(parts, key=lambda line: line.x)
    raw = " ".join(line.text.strip() for line in ordered if line.text.strip())
    raw = re.sub(r"\s+", " ", raw).strip()
    timer = _TIMER_RE.search(raw)
    difficulty = _DIFFICULTY_RE.search(raw)
    if timer is None or difficulty is None:
        return None

    tail = raw[difficulty.end():].strip()
    if tail.startswith("(") and ")" in tail:
        tail = tail.split(")", 1)[1].strip()
    else:
        tail = _VARIANT_RE.sub("", tail).strip()
    target = _target_from_event(tail)

    # Windows OCR sometimes emits each table cell separately. The rightmost
    # cell is authoritative when the combined suffix is imperfect.
    if not target:
        for part in reversed(ordered):
            target = _target_from_event(part.text)
            if target:
                tail = part.text.strip()
                break
    if not target:
        return None

    prefix = raw[timer.end():difficulty.start()].strip(" -|:")
    instance_name = re.sub(r"\s*-\s*$", "", prefix).strip()
    remaining = (
        _number(timer.group("days")) * 86400
        + _number(timer.group("hours")) * 3600
        + _number(timer.group("minutes")) * 60
        + _number(timer.group("seconds"))
    )
    return ParsedRaidLockout(
        target=target,
        difficulty=int(difficulty.group(1)),
        remaining_seconds=remaining,
        instance_name=instance_name,
        event_name=tail,
        raw_text=raw,
    )


def parse_instance_lockouts(lines: Iterable[OcrLine]) -> list[ParsedRaidLockout]:
    """Return recognized raid rows, deduplicated by boss and difficulty."""

    groups = _row_groups(lines)
    timer_lines = [
        line for parts in groups for line in parts
        if _TIMER_RE.search(line.text)
    ]
    found: dict[tuple[str, int], ParsedRaidLockout] = {}
    for parts in groups:
        raw = " ".join(line.text.strip() for line in parts)
        if (_TIMER_RE.search(raw) is None
                and _DIFFICULTY_RE.search(raw) is not None
                and any(_target_from_event(line.text) for line in parts)
                and timer_lines):
            center = sum(
                line.y + line.height / 2.0 for line in parts) / len(parts)
            nearest = min(
                timer_lines,
                key=lambda line: abs(center - (line.y + line.height / 2.0)))
            distance = abs(center - (nearest.y + nearest.height / 2.0))
            # Legends rows are approximately 15 physical pixels apart in the
            # compact table. Recover only an immediately adjacent timer cell;
            # wider gaps could cross into a different lockout duration.
            if distance <= 18.0:
                parts = [OcrLine(
                    nearest.text,
                    min(line.x for line in parts) - max(1.0, nearest.width),
                    min(line.y for line in parts),
                    nearest.width,
                    nearest.height,
                ), *parts]
        lockout = _parse_row(parts)
        if lockout is None:
            continue
        key = (normalize_target(lockout.target), lockout.difficulty)
        previous = found.get(key)
        if previous is None or lockout.remaining_seconds > previous.remaining_seconds:
            found[key] = lockout
    return sorted(found.values(), key=lambda row: (row.target, row.difficulty))


def parse_instance_character(lines: Iterable[OcrLine]) -> str:
    """Read the optional ``Leader: Name`` evidence shown in Alt+Z."""

    for parts in _row_groups(lines):
        raw = " ".join(part.text.strip() for part in sorted(parts, key=lambda item: item.x))
        # Compact UI text regularly loses the colon while preserving the two
        # cells as one row (``Leader Spin``). The exclusions below still keep
        # the nearby ``Leader Options`` heading from becoming a character.
        match = re.search(
            r"\bLeader\s*(?:[:;]\s*|\s+)([A-Za-z][A-Za-z'-]{1,31})\b",
            raw, re.I)
        if match and match.group(1).casefold() not in {"option", "options", "targeted"}:
            return match.group(1)
    return ""


__all__ = [
    "ParsedRaidLockout", "parse_instance_character", "parse_instance_lockouts",
]
