#!/usr/bin/env python3
"""Refresh Loremaster's versioned Plane of Sky quest-data snapshot."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://eqlegendstools.com/plane-of-sky-quests/"
OUTPUT = REPO / "loremaster" / "assets" / "plane_of_sky_quests.json"


def extract_rows(html: str) -> list[dict]:
    match = re.search(r"const\s+questData\s*=\s*(\[.*?\])\s*;", html, re.S)
    if not match:
        raise RuntimeError("questData was not found in the source page")
    rows = json.loads(match.group(1))
    required = {"className", "npc", "reward", "questItem", "source"}
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("questData is empty or malformed")
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not required.issubset(row):
            raise RuntimeError(f"questData row {index} is missing required fields")
    return rows


def build_payload(html: str, rows: list[dict]) -> dict:
    version = "unknown"
    found = re.search(r"\bv(\d+\.\d+\.\d+)\b", html)
    if found:
        version = found.group(1)
    compact_rows = [{key: row[key] for key in
                     ("className", "npc", "reward", "questItem", "source")}
                    for row in rows]
    return {
        "metadata": {
            "source_url": SOURCE_URL,
            "source_version": version,
            "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "runtime_network_required": False,
        },
        "rows": compact_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path,
                        help="Read saved source HTML instead of downloading")
    args = parser.parse_args()
    if args.input:
        html = args.input.read_text(encoding="utf-8")
    else:
        request = urllib.request.Request(
            SOURCE_URL, headers={"User-Agent": "SpinUI-Loremaster-data-refresh/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            html = response.read().decode("utf-8")
    rows = extract_rows(html)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_payload(html, rows), indent=2,
                                 ensure_ascii=False) + "\n", encoding="utf-8")
    rewards = {(r["className"], r["npc"], r["reward"]) for r in rows}
    items = {r["questItem"] for r in rows}
    print(f"wrote {OUTPUT}: {len(rows)} rows, {len(rewards)} rewards, {len(items)} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
