#!/usr/bin/env python3
"""Read one version's entry out of CHANGELOG.md.

The release workflow prepends this to a release's notes, so what a change was
for is written once, in the pull request that makes it, and is then carried by
every build that ships it -- the candidate and the release it is promoted to
both read the same entry, because both resolve to the same base version.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHANGELOG = REPO / "CHANGELOG.md"
HEADING = re.compile(r"^## +(?P<version>\S+)", re.MULTILINE)


def base_version(version: str) -> str:
    """Strip a prerelease suffix: 0.4.0-rc.1 and 0.4.0 share one entry."""
    return re.sub(r"[-+].*$", "", str(version).strip().lstrip("v"))


def entry(text: str, version: str) -> str:
    """The body under ``## <version>``, or "" when there is no such heading."""
    wanted = base_version(version)
    matches = list(HEADING.finditer(text))
    for index, match in enumerate(matches):
        if base_version(match.group("version")) != wanted:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return text[start:end].strip("\n").strip()
    return ""


def _force_utf8_streams() -> None:
    """Emit UTF-8 whatever the console codepage says.

    PowerShell decodes a native command's stdout as UTF-8, but Python encodes
    its own stdout with the ANSI codepage when it is redirected on Windows.
    An em dash left here as a lone 0x97, which is not valid UTF-8, so every one
    of them reached the release page as U+FFFD -- seven of them on v0.4.0, and
    the same on both candidates before it.  Reading CHANGELOG.md was never the
    problem; leaving this process was.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _self_test_stdout_encoding() -> None:
    """The entry has to survive leaving this process, not just being found."""
    if not CHANGELOG.is_file():
        return
    text = CHANGELOG.read_text(encoding="utf-8")
    heading = HEADING.search(text)
    assert heading is not None, "CHANGELOG.md has no version heading"
    version = heading.group("version")
    # cp1252 is what a Windows runner hands Python when stdout is a pipe, and
    # it is where the release notes were being corrupted.
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--version", version],
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        capture_output=True, check=True,
    )
    # Two separate claims, so a failure says which one broke.  Decoding is the
    # invariant under test; the content check guards against fixing the bytes
    # by mangling the text.  Windows translates \n to \r\n on the way out of a
    # text-mode stdout, which is not corruption -- the workflow rejoins lines
    # anyway -- so it is normalized before comparing.
    try:
        produced = result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AssertionError(
            f"release notes are not UTF-8 on the way out: {exc}") from exc
    assert produced.replace("\r\n", "\n").strip("\n") == entry(text, version), (
        "release notes changed on the way out")


def _self_test() -> int:
    sample = "\n".join((
        "# Changelog", "",
        "## 0.4.0", "",
        "First entry.", "",
        "- a bullet", "",
        "## 0.3.4", "",
        "Older entry.",
    ))
    assert entry(sample, "0.4.0").startswith("First entry.")
    assert "- a bullet" in entry(sample, "0.4.0")
    # A candidate reads its own release's entry, which is the whole point.
    assert entry(sample, "0.4.0-rc.1") == entry(sample, "0.4.0")
    assert entry(sample, "v0.4.0-rc.2") == entry(sample, "0.4.0")
    # The next version's entry must not leak into this one.
    assert "Older entry." not in entry(sample, "0.4.0")
    assert entry(sample, "0.3.4") == "Older entry."
    # A missing entry is reported, never guessed at.
    assert entry(sample, "9.9.9") == ""
    # The last entry in the file runs to the end of it.
    assert entry("## 1.0.0\n\nOnly entry.\n", "1.0.0") == "Only entry."
    _self_test_stdout_encoding()
    print("release notes extractor: ALL PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="release version or tag, e.g. v0.4.0-rc.1")
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero when the entry is missing, print nothing")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    _force_utf8_streams()
    if args.self_test:
        return _self_test()
    if not args.version:
        parser.error("--version is required")
    if not CHANGELOG.is_file():
        print(f"{CHANGELOG.name} does not exist", file=sys.stderr)
        return 1
    found = entry(CHANGELOG.read_text(encoding="utf-8"), args.version)
    if not found:
        print(
            f"CHANGELOG.md has no '## {base_version(args.version)}' entry, so this "
            "release would ship without saying what it is for. Add one and run again.",
            file=sys.stderr)
        return 1
    if not args.check:
        print(found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
