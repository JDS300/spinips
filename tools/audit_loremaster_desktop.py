#!/usr/bin/env python3
"""Static contract for the Electron Loremaster themes and supported tracking.

This audit intentionally checks the seams where a partially implemented theme
can look correct in the main window while leaving the Seed, alerts, or archive
on the old palette.  It also keeps the retired Instance Information screen OCR
from returning through a stale hotkey or protocol field.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
DESKTOP = REPO / "loremaster-desktop"


class AuditFailure(RuntimeError):
    pass


def fail(message: str) -> None:
    raise AuditFailure(message)


def read(relative: str) -> str:
    path = REPO / relative
    if not path.is_file():
        fail(f"required source is missing: {relative}")
    return path.read_text(encoding="utf-8")


def require(source: str, values: tuple[str, ...], owner: str) -> None:
    missing = [value for value in values if value not in source]
    if missing:
        fail(f"{owner} is missing: " + ", ".join(missing))


def audit_theme_contract() -> None:
    protocol = read("loremaster-desktop/src/protocol.ts")
    app = read("loremaster-desktop/src/App.tsx")
    renderer = read("loremaster-desktop/src/main.tsx")
    electron = read("loremaster-desktop/electron/main.ts")
    preload = read("loremaster-desktop/electron/preload.ts")
    base_styles = read("loremaster-desktop/src/styles.css")
    themes = read("loremaster-desktop/src/themes.css")
    readme = read("loremaster-desktop/README.md")

    if not re.search(
        r'type\s+LoremasterTheme\s*=\s*["\']vellum["\']\s*\|\s*["\']glass["\']',
        protocol,
    ):
        fail("protocol must expose the exact vellum | glass theme union")
    require(protocol, ("uiTheme: LoremasterTheme",), "renderer protocol")
    require(
        electron,
        ("uiTheme", '"vellum"', '"glass"', "settings:changed"),
        "Electron settings persistence",
    )
    if electron.count("uiTheme") < 6:
        fail("Electron does not normalize, persist, update, and seed the theme")
    require(
        app,
        (
            "VELLUM & EMBER",
            "MIDNIGHT FROST GLASS",
            "SpinUI Reloaded",
            "SpinUI Glass",
            'role="radiogroup"',
            "uiTheme",
        ),
        "Settings theme picker",
    )
    require(
        app,
        (
            "ALERT SOUND STUDIO",
            "Rune Pulse",
            "Crystal Chime",
            "Ember Alarm",
            "Temple Bell",
            "sound-preset-trigger",
            "sound-preset-menu",
            'aria-haspopup="listbox"',
            "previewConfiguredSound",
            "soundKindForAlert",
        ),
        "per-alert sound studio",
    )
    require(
        protocol,
        ("AlertSoundKind", "AlertSoundPreset", "soundProfiles"),
        "sound profile protocol",
    )
    require(
        electron,
        (
            "alerts:choose-sound",
            "alerts:read-sound",
            "CUSTOM_SOUND_MAX_BYTES",
            "normalizeSoundProfiles",
        ),
        "custom sound boundary",
    )
    require(
        preload,
        ("chooseAlertSound", "readAlertSound"),
        "custom sound preload API",
    )
    if 'role="radio"' not in app and "aria-pressed" not in app:
        fail("theme choices need an accessible selected-state contract")
    if app.count("applyTheme(") < 4:
        fail("theme is not applied to all main, alert, and control surfaces")
    require(
        renderer,
        ("data", "theme", "document.documentElement"),
        "pre-render theme seed",
    )
    if renderer.count('import "./themes.css";') != 1:
        fail("theme stylesheet must be imported exactly once after the base CSS")
    if not re.search(r"\.settings-toggle\s*\{[^}]*position:\s*relative", base_styles):
        fail("Settings toggles need a local containing block to prevent focus-scroll blanks")
    require(
        base_styles,
        (".settings-toggle input", "width: 1px", "height: 1px", "clip-path: inset(50%)"),
        "accessible Settings toggle concealment",
    )

    lowered = themes.casefold()
    require(
        lowered,
        (
            '[data-theme="glass"]',
            "#0c0906",
            "#130e09",
            "#685030",
            "#d0a254",
            "#f1e7d4",
            "#03080e",
            "#060f18",
            "#30798f",
            "#69e1f2",
            "#55f2be",
            "#ab80ff",
            "#e8f8fc",
            "--danger",
            "--warning",
            "--success",
        ),
        "canonical theme palette",
    )
    for selector in (
        ".rune-seed",
        ".loremaster-shell",
        ".settings-card",
        ".alert-surface",
        ".seed-control-surface",
        ".seed-group-surface",
        ".weekly-card",
        ".gear-card",
        ".archive-shell",
        ".archive-fights",
        ".archive-report",
        ".theme-picker",
        ".theme-option",
    ):
        if selector not in themes:
            fail(f"theme stylesheet does not cover {selector}")
    if "backdrop-filter" in lowered:
        fail("transparent Electron windows must not depend on live blur")
    require(
        readme,
        ("Vellum & Ember", "Midnight Frost Glass", "spinui_reloaded", "spinui_glass", "Alert Sound Studio"),
        "Loremaster desktop documentation",
    )


def audit_retired_lockout_ocr() -> None:
    runtime_sources = {
        "Electron main": read("loremaster-desktop/electron/main.ts"),
        "renderer": read("loremaster-desktop/src/App.tsx"),
        "protocol": read("loremaster-desktop/src/protocol.ts"),
        "desktop worker": read("loremaster/desktop_worker.py"),
    }
    forbidden = (
        "scan-alt-z",
        "scanAltZ",
        "altZLockout",
        "altZScan",
        "instance_lockout_ocr",
        "instance_lockouts",
        "globalShortcut",
    )
    for owner, source in runtime_sources.items():
        found = [value for value in forbidden if value.casefold() in source.casefold()]
        if found:
            fail(f"{owner} still contains retired lockout OCR: {', '.join(found)}")
    for relative in (
        "loremaster/instance_lockout_ocr.py",
        "loremaster/tests/test_instance_lockout_ocr.py",
    ):
        if (REPO / relative).exists():
            fail(f"retired lockout OCR file still exists: {relative}")


def main() -> int:
    try:
        audit_theme_contract()
        audit_retired_lockout_ocr()
    except AuditFailure as exc:
        print(f"Loremaster desktop audit: FAIL\n  {exc}", file=sys.stderr)
        return 1
    print("Loremaster desktop audit: ALL PASS")
    print("  Vellum & Ember + Midnight Frost Glass | persistent cross-window themes")
    print("  no Instance Information OCR or reserved Ctrl+Shift+Z shortcut")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
