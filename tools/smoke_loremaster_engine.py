#!/usr/bin/env python3
"""Launch a packaged Loremaster engine and validate its JSONL handshake."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--log-path", default="")
    parser.add_argument("--expect-active-log", default="")
    args = parser.parse_args()
    executable = args.executable.resolve()
    if not executable.is_file():
        raise SystemExit(f"engine executable not found: {executable}")
    process = subprocess.Popen(
        [str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8")
    assert process.stdin is not None
    process.stdin.write(json.dumps({
        "type": "engine.initialize", "logPath": args.log_path,
        "raidDifficulty": None}) + "\n")
    process.stdin.flush()
    time.sleep(1.5 if args.expect_active_log else 0.25)
    process.stdin.write(json.dumps({"type": "engine.shutdown"}) + "\n")
    process.stdin.flush()
    stdout, stderr = process.communicate(timeout=15)
    if process.returncode != 0:
        raise SystemExit(
            f"engine exited {process.returncode}: {stderr.strip()}")
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    if not events or events[0].get("eventType") != "engine.ready":
        raise SystemExit(f"invalid engine handshake: {events!r}")
    if any(event.get("protocolVersion") != 1 for event in events):
        raise SystemExit("engine protocol mismatch")
    if args.expect_active_log:
        expected = str(Path(args.expect_active_log).resolve()).casefold()
        active_paths = [
            str(event.get("health", {}).get("activeLogPath", "")).casefold()
            for event in events if isinstance(event.get("health"), dict)
        ]
        if expected not in active_paths:
            raise SystemExit(
                f"packaged engine did not activate expected log {expected}: "
                f"{active_paths[-4:]}")
    print(f"LoremasterEngine JSONL smoke: PASS | {len(events)} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
