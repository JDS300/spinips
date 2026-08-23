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
import re
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
# inside a Wine or Proton prefix. Mirrors what the desktop app already probes.
PREFIX_PARENTS = (
    "~/.wine", "~/Games", "~/.local/share/Steam/steamapps/compatdata",
    "~/.steam/steam/steamapps/compatdata",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata",
)
# EverQuest folder shapes inside a prefix's drive_c.
EQ_SHAPES = (
    "users/Public/Daybreak Game Company/Installed Games/EverQuest Legends",
    "users/Public/Daybreak Game Company/Installed Games/EverQuest",
    "users/steamuser/Daybreak Game Company/Installed Games/EverQuest Legends",
    "users/steamuser/Daybreak Game Company/Installed Games/EverQuest",
    "Program Files (x86)/Daybreak Game Company/Installed Games/EverQuest Legends",
    "Program Files (x86)/Daybreak Game Company/Installed Games/EverQuest",
    "EQLegends", "EverQuest",
)


def lutris_prefix_roots() -> list[Path]:
    """Prefix paths declared in Lutris game configs.

    Lutris routinely puts a prefix on another drive entirely, so a
    home-relative probe never sees it -- which is exactly how this tool missed
    a live EverQuest Legends install sitting under /mnt. The desktop app reads
    these already; this mirrors it rather than reimplementing discovery.
    """

    roots: list[Path] = []
    for directory in ("~/.local/share/lutris/games",
                      "~/.var/app/net.lutris.Lutris/data/lutris/games"):
        base = Path(directory).expanduser()
        if not base.is_dir():
            continue
        for config in base.glob("*.yml"):
            try:
                text = config.read_text(errors="replace")
            except OSError:
                continue
            for match in re.finditer(r"^\s*prefix:\s*(\S.*?)\s*$", text, re.M):
                candidate = Path(match.group(1).strip().strip("'\""))
                if candidate.is_absolute():
                    roots.append(candidate)
    return roots


def prefix_roots() -> list[Path]:
    roots = list(lutris_prefix_roots())
    for parent in PREFIX_PARENTS:
        base = Path(parent).expanduser()
        if not base.is_dir():
            continue
        roots.append(base)
        for child in base.iterdir():
            if child.is_dir():
                roots.append(child)
                roots.append(child / "pfx")
    return roots


def discover() -> list[Path]:
    """Every eqlog_*.txt we can find, newest first."""

    found: list[Path] = []
    for directory in APP.DEFAULT_LOG_DIRS:
        base = Path(directory)
        for candidate in (base, base / "Logs"):
            if candidate.is_dir():
                found.extend(candidate.glob("eqlog_*.txt"))

    seen: set[Path] = set()
    for root in prefix_roots():
        drive = root / "drive_c"
        if not drive.is_dir():
            drive = root if (root / "users").is_dir() else drive
        if not drive.is_dir() or drive in seen:
            continue
        seen.add(drive)
        for shape in EQ_SHAPES:
            game = drive / shape
            for candidate in (game, game / "Logs"):
                if candidate.is_dir():
                    found.extend(candidate.glob("eqlog_*.txt"))

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
            print("Searched these prefixes:", file=sys.stderr)
            for d in prefix_roots()[:20]:
                print(f"  {d}", file=sys.stderr)
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
    dot_names = Counter()        # your own, from dot_out
    other_dot_names = Counter()  # somebody else's, from dot_third
    landing_examples: dict[str, str] = {}
    unparsed_candidates: list[str] = []

    landing_kinds = set(APP.DEBUFF_LANDING_KINDS)
    # Prose that looks like it could be a debuff landing but matched nothing.
    # Anchored to a trailing period so ordinary chat does not qualify -- an
    # earlier version flagged every line from a player called Sleepyjoe.
    suspicious = re.compile(
        r"(yawns|slows down|feels lethargic|looks (somewhat |very )?uncomfortable"
        r"|glances nervously about)\.$")

    for line in lines:
        parsed = APP.parse_line(line)
        if parsed is None:
            body = line.split("] ", 1)[-1]
            if suspicious.search(body):
                unparsed_candidates.append(body)
            continue
        _ts, kind, groups = parsed
        kinds[kind] += 1
        if kind == "cast_begin":
            cast_names[groups.get("spell", "")] += 1
        elif kind == "song_begin":
            cast_names[groups.get("song", "")] += 1
        elif kind == "dot_out":
            dot_names[groups.get("spell", "")] += 1
        elif kind == "dot_third":
            # Carries "by <caster>": somebody else's DoT, which never reaches
            # the deck. Counted separately so it cannot look like a gap.
            other_dot_names[groups.get("spell", "")] += 1
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

    print("== 3. Your DoT ticks, and whether the table knows them ==")
    if not dot_names:
        print("  no DoT damage lines in this window.")
    for name, count in dot_names.most_common(30):
        resolved = resolve_debuff_spell(name)
        mark = "TRACKED  " if resolved else "UNKNOWN  "
        print(f"  {mark}{name:34s} x{count}")
    if dot_names and not any(resolve_debuff_spell(n) for n in dot_names):
        print("  ^ none recognised: the table does not cover these spells.")
    print()

    if other_dot_names:
        print("  Other players' DoTs seen on the same mobs (never tracked, by design):")
        for name, count in other_dot_names.most_common(8):
            print(f"    {name:34s} x{count}")
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
