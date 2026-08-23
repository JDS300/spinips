#!/usr/bin/env python3
"""Report what the debuff tracker actually sees in a real EverQuest log.

Debuff timers can fail silently: an unrecognised spell name or unmatched
landing line produces no row and no error, which looks identical to "the
feature is off".  This walks a real log and says which of those it is.

Usage:
    python3 tools/diagnose_debuff_timers.py                  # auto-discover
    python3 tools/diagnose_debuff_timers.py path/to/eqlog.txt
    python3 tools/diagnose_debuff_timers.py --lines 200000   # scan further back

Nothing is uploaded and nothing is written; it only reads.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOREMASTER = REPO / "loremaster"
sys.path.insert(0, str(LOREMASTER))

_spec = importlib.util.spec_from_file_location(
    "loremaster_diagnose_app", LOREMASTER / "loremaster.py")
APP = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = APP
_spec.loader.exec_module(APP)

from debuff_timer import (  # noqa: E402
    DEBUFF_LANDING_COMPATIBILITY, DEBUFF_SPELLS, resolve_debuff_spell)


# Windows paths in DEFAULT_LOG_DIRS mean nothing on Linux, where the game runs
# inside a Wine or Proton prefix. Search the prefixes themselves.
PREFIX_ROOTS = (
    "~/.wine/drive_c",
    "~/Games",
    "~/.local/share/Steam/steamapps/compatdata",
    "~/.steam/steam/steamapps/compatdata",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata",
    "~/.var/app/net.lutris.Lutris",
    "~/EverQuest Legends",
)


def discover() -> list[Path]:
    """Every eqlog_*.txt we can find, newest first."""

    found: list[Path] = []
    for directory in APP.DEFAULT_LOG_DIRS:
        base = Path(directory)
        for candidate in (base, base / "Logs"):
            if candidate.is_dir():
                found.extend(candidate.glob("eqlog_*.txt"))
    for root in PREFIX_ROOTS:
        base = Path(root).expanduser()
        if not base.is_dir():
            continue
        # Bounded so a large prefix tree cannot hang the scan.
        for depth in range(1, 8):
            pattern = "/".join(["*"] * depth) + "/eqlog_*.txt"
            try:
                found.extend(base.glob(pattern))
            except OSError:
                break
    return sorted({f.resolve() for f in found if f.is_file()},
                  key=lambda p: p.stat().st_mtime, reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", nargs="?", type=Path)
    parser.add_argument("--lines", type=int, default=120000,
                        help="how many trailing lines to scan (default 120000)")
    args = parser.parse_args()

    log = args.log
    if log is None:
        candidates = discover()
        if not candidates:
            print("No eqlog_*.txt found in the usual places. Pass a path.",
                  file=sys.stderr)
            print("Searched Wine/Proton prefixes:", file=sys.stderr)
            for d in PREFIX_ROOTS:
                marker = "" if Path(d).expanduser().is_dir() else "  (absent)"
                print(f"  {d}{marker}", file=sys.stderr)
            print("\nIf EQ logging is off, there is no file to find: type"
                  " /log on in game.", file=sys.stderr)
            return 2
        log = candidates[0]
        if len(candidates) > 1:
            print(f"note: {len(candidates)} logs found, using the most recent")
    if not log.is_file():
        print(f"not a file: {log}", file=sys.stderr)
        return 2

    print(f"log: {log}")
    raw = log.read_text(encoding="utf-8", errors="replace").splitlines()
    lines = raw[-args.lines:]
    print(f"scanning {len(lines):,} of {len(raw):,} lines\n")

    kinds = Counter()
    cast_names = Counter()
    dot_names = Counter()
    landing_examples: dict[str, str] = {}
    unparsed_candidates: list[str] = []

    landing_kinds = set(APP.DEBUFF_LANDING_KINDS)
    # Prose that looks like it could be a debuff landing but matched nothing.
    suspicious = ("yawn", "slows down", "lethargic", "uncomfortable",
                  "glances nervously", "sleepy", "slowed")

    for line in lines:
        parsed = APP.parse_line(line)
        if parsed is None:
            body = line.split("] ", 1)[-1]
            if any(word in body.lower() for word in suspicious):
                unparsed_candidates.append(body)
            continue
        _ts, kind, groups = parsed
        kinds[kind] += 1
        if kind == "cast_begin":
            cast_names[groups.get("spell", "")] += 1
        elif kind == "song_begin":
            cast_names[groups.get("song", "")] += 1
        elif kind in ("dot_out", "dot_third"):
            dot_names[groups.get("spell", "")] += 1
        elif kind in landing_kinds:
            landing_examples.setdefault(kind, line.split("] ", 1)[-1])

    print("== 1. Did any debuff landing line parse? ==")
    if landing_examples:
        for kind, example in sorted(landing_examples.items()):
            print(f"  {kind:28s} e.g. {example}")
    else:
        print("  none. No slow/resist landing prose in this log.")
    if unparsed_candidates:
        print("\n  Lines that LOOK like a landing but matched no pattern:")
        for body in sorted(set(unparsed_candidates))[:10]:
            print(f"    {body!r}")
        print("  ^ these are the strings the regexes need to be built from.")
    print()

    print("== 2. Your own casts, and whether the table knows them ==")
    if not cast_names:
        print("  no 'You begin casting' lines at all in this window.")
    tracked = untracked = 0
    for name, count in cast_names.most_common(40):
        resolved = resolve_debuff_spell(name)
        if resolved:
            tracked += 1
            print(f"  TRACKED    {name:34s} x{count:<5d} {resolved.kind}")
        else:
            untracked += 1
    if untracked:
        print(f"\n  Not in the debuff table ({untracked} distinct):")
        for name, count in cast_names.most_common(40):
            if not resolve_debuff_spell(name):
                print(f"    {name:34s} x{count}")
        print("  ^ a debuff here means the table is missing it or the name differs.")
    print()

    print("== 3. DoT ticks, and whether the table knows them ==")
    if not dot_names:
        print("  no DoT damage lines in this window.")
    for name, count in dot_names.most_common(30):
        resolved = resolve_debuff_spell(name)
        mark = "TRACKED  " if resolved else "UNKNOWN  "
        print(f"  {mark}{name:34s} x{count}")
    if dot_names and not any(resolve_debuff_spell(n) for n in dot_names):
        print("  ^ none recognised: the table does not cover these spells.")
    print()

    print("== 4. Table coverage ==")
    by_kind = Counter(s.kind for s in DEBUFF_SPELLS)
    print(f"  {len(DEBUFF_SPELLS)} spells: " +
          ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    print(f"  landing families: {', '.join(sorted(DEBUFF_LANDING_COMPATIBILITY))}")
    print()

    print("== 5. Most common parsed line kinds (sanity check) ==")
    for kind, count in kinds.most_common(12):
        print(f"  {kind:28s} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
