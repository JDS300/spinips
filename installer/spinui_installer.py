#!/usr/bin/env python3
"""Windows installer for Spin's UI Reloaded and Spin's Loremaster.

The packaged executable sits beside the release payload. It discovers common
EverQuest installations, installs the skin and Loremaster, optionally applies
a validated resolution/layout profile with a backup, and can register
Loremaster to wait quietly for eqgame.exe at Windows sign-in.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "SpinUI Installer"
SKIN_NAME = "spinui_reloaded"
# The only skin folders shipped in the release payload. Layout presets are
# only audited against SKIN_NAME today (see _validate_source_value), so
# selecting the other skin and a layout preset together fails closed instead
# of silently writing a mismatched UISkin.
AVAILABLE_SKINS: tuple[str, ...] = (SKIN_NAME, "spinui_glass")
LAYOUT_NAME = "UI_Spin_qeynos_LO1.ini"
LOREMASTER_NAME = "Loremaster.exe"  # Windows only; loremaster-desktop's win target.
# loremaster-desktop ships a native Linux build too, never run under Wine.
# electron-builder names it Loremaster-<version>-<arch>.<ext>, and the
# version/arch vary per release tag, so it is matched by glob rather than a
# fixed filename. AppImage is preferred: it is one self-contained executable
# file, so nothing needs to be extracted before a shortcut can launch it.
LOREMASTER_LINUX_ARTIFACT_GLOB = "Loremaster-*.AppImage"
LOREMASTER_LINUX_TARBALL_GLOB = "Loremaster-*.tar.gz"
LOREMASTER_LINUX_DESTINATION_NAME = "Loremaster.AppImage"
# loremaster-desktop/package.json's linux.executableName: the process name
# the running AppImage reports in /proc, independent of its filename on disk.
LOREMASTER_LINUX_PROCESS_NAME = "loremaster"
# Windows uses a .lnk; freedesktop environments use a .desktop entry instead.
STARTUP_LINK = "Spin's Loremaster.lnk" if os.name == "nt" else "Spin's Loremaster.desktop"
DESKTOP_LINK = "Spin's Loremaster.lnk" if os.name == "nt" else "Spin's Loremaster.desktop"

BG = "#120d08"
PANEL = "#1a140d"
RAISED = "#261d12"
LINE = "#685030"
GOLD = "#d0a254"
GOLD_BRIGHT = "#f8d68c"
CYAN = "#7eaaf4"
TEXT = "#f1e7d4"
DIM = "#ac9a7e"
EMBER = "#f2762c"


@dataclass(frozen=True)
class LayoutPreset:
    """One public, installer-selectable chat emphasis."""

    key: str
    title: str
    tagline: str
    chat_widths: tuple[int, int, int]
    chat_heights: tuple[int, int, int] = (280, 280, 280)


KEEP_LAYOUT = "keep-existing"
DEFAULT_LAYOUT_PRESET = "combat-focus"
LAYOUT_PRESETS: dict[str, LayoutPreset] = {
    "combat-focus": LayoutPreset(
        "combat-focus", "COMBAT FOCUS", "Larger combat pane, matching Spin's live HUD.",
        (700, 700, 1060),
    ),
    "social-focus": LayoutPreset(
        "social-focus", "SOCIAL FOCUS", "More room for group, guild, and raid chat.",
        (620, 1120, 720),
    ),
    "hybrid": LayoutPreset(
        "hybrid", "HYBRID", "A compact combat ticker with balanced chat.",
        (820, 1000, 640), (280, 280, 200),
    ),
}


@dataclass(frozen=True)
class ResolutionProfile:
    key: str
    width: int
    height: int
    label: str


DEFAULT_RESOLUTION_PROFILE = "3440x1440"
RESOLUTION_PROFILES: dict[str, ResolutionProfile] = {
    "1920x1080": ResolutionProfile(
        "1920x1080", 1920, 1080, "1920×1080 · Full HD"),
    "2048x1080": ResolutionProfile(
        "2048x1080", 2048, 1080, "2048×1080 · Wide Full HD"),
    "2560x1080": ResolutionProfile(
        "2560x1080", 2560, 1080, "2560×1080 · Ultrawide"),
    "2560x1440": ResolutionProfile(
        "2560x1440", 2560, 1440, "2560×1440 · QHD"),
    "3440x1440": ResolutionProfile(
        "3440x1440", 3440, 1440, "3440×1440 · Ultrawide QHD"),
    "3840x1600": ResolutionProfile(
        "3840x1600", 3840, 1600, "3840×1600 · Ultrawide"),
    "3840x2160": ResolutionProfile(
        "3840x2160", 3840, 2160, "3840×2160 · 4K"),
}
PROFILE_LABEL_TO_KEY = {
    profile.label: profile.key for profile in RESOLUTION_PROFILES.values()
}
PROFILE_KEY_TO_LABEL = {
    profile.key: profile.label for profile in RESOLUTION_PROFILES.values()
}


@dataclass(frozen=True)
class LegendsServer:
    display: str
    token: str


LEGENDS_SERVERS: tuple[LegendsServer, ...] = (
    LegendsServer("Erudin (European)", "erudin"),
    LegendsServer("Freeport", "freeport"),
    LegendsServer("Halas", "halas"),
    LegendsServer("Neriak", "neriak"),
    LegendsServer("Oggok", "oggok"),
    LegendsServer("Paineel (European)", "paineel"),
    LegendsServer("Qeynos", "qeynos"),
    LegendsServer("Rivervale", "rivervale"),
)
SERVER_TOKEN_BY_DISPLAY = {server.display: server.token for server in LEGENDS_SERVERS}

# Deliberately mirrors tools/generate_spinui_layout.py::PLACEMENTS plus its
# separately-generated EQMAIN placement. Existing character INIs receive
# audited layout values (geometry plus visibility) for these windows, and the
# preset's complete [ChatManager] chat routing. Every other section remains
# byte-for-byte user-owned.
LAYOUT_GEOMETRY_SECTIONS = frozenset({
    "AggroMeterWnd", "BagBank1", "BagBank2", "BagBank3", "BagBank4",
    "BagBank5", "BagBank6", "BagBank7", "BagBank8", "BagBank9",
    "BagBank10", "BagBank11", "BagBank12", "BagBank13", "BagBank14",
    "BagBank15", "BagBank16", "BagInv1", "BagInv2", "BagInv3",
    "BagInv4", "BagInv5", "BagInv6", "BagInv7", "BagInv8", "BigBankWnd",
    "BreathWindow", "BuffWindow", "BuffWindow_13", "CastSpellWnd",
    "CastingWindow", "Chat 1", "Chat 2", "Chat 3", "CompassWindow",
    "EQMainWnd", "ExtendedTargetWnd", "GroupWindow", "HotButtonWnd", "HotButtonWnd2",
    "HotButtonWnd3", "HotButtonWnd4", "HotButtonWnd5", "HotButtonWnd6",
    "HotButtonWnd7", "HotButtonWnd8", "HotButtonWnd9", "HotButtonWnd10",
    "HotButtonWnd11", "InventoryWindow", "MainChat", "MapViewWnd",
    "PetInfoWindow", "PetInfoWindow_1", "PetInfoWindow_2", "PetInfoWindow_3",
    "PlayerWindow", "ShortDurationBuffWindow",
    "ShortDurationBuffWindow_13", "StanceWnd", "TargetOfTargetWindow",
    "TargetWindow", "TrackingWnd",
})
GEOMETRY_KEYS = ("XRef", "YRef", "XPos", "YPos", "Width", "Height")
VISIBILITY_KEYS = ("Show", "Alpha", "FadeToAlpha", "Fades")
LAYOUT_KEYS = GEOMETRY_KEYS + VISIBILITY_KEYS
MERGE_KEY_ORDER = ("INIVersion", "UISkin") + LAYOUT_KEYS
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL", "CLOCK$",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class IniDocument:
    data: bytes
    text: str
    encoding: str
    bom: bytes
    newline: str
    had_final_newline: bool
    lines: tuple[str, ...]
    sections: dict[str, tuple[int, int, str]]
    keys: dict[tuple[str, str], int]


@dataclass(frozen=True)
class PresetLayout:
    """Validated preset content inside the audited merge boundary.

    ``sections`` maps audited section names to their layout key/value pairs;
    ``chat_lines`` is the preset's complete [ChatManager] body, carried
    wholesale into the target.
    """

    sections: dict[str, dict[str, str]]
    chat_lines: tuple[str, ...]


@dataclass(frozen=True)
class LayoutUpdate:
    target: Path
    original: bytes | None
    updated: bytes
    changed: bool
    created: bool


def validate_character_name(value: str) -> str:
    """Accept a conservative EQ-safe character name while preserving casing."""
    if value != value.strip():
        raise ValueError("Character name cannot begin or end with spaces.")
    name = value
    if not re.fullmatch(r"[A-Za-z]{1,32}", name):
        raise ValueError("Character name must contain 1–32 English letters only.")
    if name.upper() in WINDOWS_RESERVED_NAMES:
        raise ValueError("That character name is reserved by Windows.")
    return name


def manual_layout_filename(character: str, server_token: str, loadout: int = 1) -> str:
    character = validate_character_name(character)
    valid_tokens = {server.token for server in LEGENDS_SERVERS}
    if server_token not in valid_tokens:
        raise ValueError("Choose one of the supported EverQuest Legends servers.")
    if not isinstance(loadout, int) or not 1 <= loadout <= 99:
        raise ValueError("Layout number must be between 1 and 99.")
    return f"UI_{character}_{server_token}_LO{loadout}.ini"


def _decode_ini(data: bytes, label: str) -> tuple[str, str, bytes]:
    if b"\x00" in data:
        raise ValueError(f"{label} uses an unsupported encoding.")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8", b"\xef\xbb\xbf"
    try:
        return data.decode("utf-8"), "utf-8", b""
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252"), "cp1252", b""
        except UnicodeDecodeError as exc:
            raise ValueError(f"{label} is not valid UTF-8 or Windows-1252.") from exc


def _parse_ini(data: bytes, label: str) -> IniDocument:
    text, encoding, bom = _decode_ini(data, label)
    crlf = text.count("\r\n")
    bare_lf = text.count("\n") - crlf
    newline = "\r\n" if crlf >= bare_lf and crlf else "\n"
    lines = tuple(text.splitlines(keepends=True))
    if text and not lines:
        lines = (text,)
    section_headers: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        stripped = content.strip()
        if not stripped or stripped.startswith((";", "#")):
            continue
        if stripped.startswith("["):
            match = re.fullmatch(r"\[([^\]\r\n]+)\][ \t]*(?:[;#].*)?", stripped)
            if not match:
                raise ValueError(f"{label} has a malformed section header on line {index + 1}.")
            section_name = match.group(1).strip()
            section_headers.append((index, section_name.casefold(), section_name))

    audited = {name.casefold() for name in LAYOUT_GEOMETRY_SECTIONS} | {"main", "chatmanager"}
    counts: dict[str, int] = {}
    for _index, folded, _display in section_headers:
        if folded in audited:
            counts[folded] = counts.get(folded, 0) + 1
            if counts[folded] > 1:
                raise ValueError(f"{label} contains duplicate audited section [{_display}].")

    sections: dict[str, tuple[int, int, str]] = {}
    keys: dict[tuple[str, str], int] = {}
    for header_index, (start, folded, display) in enumerate(section_headers):
        end = section_headers[header_index + 1][0] if header_index + 1 < len(section_headers) else len(lines)
        sections[folded] = (start, end, display)
        if folded not in audited:
            continue
        if folded == "main":
            allowed = {"uiskin"}
        elif folded == "chatmanager":
            # ChatManager is carried wholesale, never key-by-key.
            allowed: set[str] = set()
        else:
            allowed = {"iniversion", *(key.casefold() for key in LAYOUT_KEYS)}
        for line_index in range(start + 1, end):
            content = lines[line_index].rstrip("\r\n")
            stripped = content.strip()
            if not stripped or stripped.startswith((";", "#")) or "=" not in content:
                continue
            raw_key = content.split("=", 1)[0].strip()
            key_folded = raw_key.casefold()
            if key_folded not in allowed:
                continue
            key_id = (folded, key_folded)
            if key_id in keys:
                raise ValueError(
                    f"{label} contains duplicate audited key {raw_key} in [{display}]."
                )
            keys[key_id] = line_index
    return IniDocument(
        data=data, text=text, encoding=encoding, bom=bom, newline=newline,
        had_final_newline=text.endswith(("\n", "\r")), lines=lines,
        sections=sections, keys=keys,
    )


def _raw_value(line: str) -> str:
    content = line.rstrip("\r\n")
    value = content.split("=", 1)[1].strip()
    markers = [position for marker in ";#" if (position := value.find(marker)) >= 0]
    if markers:
        value = value[:min(markers)].rstrip()
    return value


def _validate_source_value(key: str, value: str, section: str, *,
                           expected_skin: str = SKIN_NAME) -> None:
    if key == "UISkin":
        if section.casefold() != "main" or value != expected_skin:
            raise ValueError(f"Preset [Main] UISkin must be exactly {expected_skin}.")
        return
    if key == "INIVersion":
        if not value.isdigit() or not 1 <= int(value) <= 99:
            raise ValueError(f"Preset [{section}] has an invalid INIVersion.")
        return
    if key == "XRef" and value.casefold() not in {"left", "center", "right"}:
        raise ValueError(f"Preset [{section}] has an invalid XRef.")
    if key == "YRef" and value.casefold() not in {"top", "center", "bottom"}:
        raise ValueError(f"Preset [{section}] has an invalid YRef.")
    if key in {"XPos", "YPos"}:
        if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)%", value):
            raise ValueError(f"Preset [{section}] has an invalid {key}.")
        numeric = float(value[:-1])
        if not -500 <= numeric <= 500:
            raise ValueError(f"Preset [{section}] has an out-of-range {key}.")
    if key in {"Width", "Height"}:
        if not value.isdigit() or not 1 <= int(value) <= 10000:
            raise ValueError(f"Preset [{section}] has an invalid {key}.")
    if key in {"Show", "Fades"} and value not in {"0", "1"}:
        raise ValueError(f"Preset [{section}] has an invalid {key}.")
    if key in {"Alpha", "FadeToAlpha"}:
        if not value.isdigit() or not 0 <= int(value) <= 255:
            raise ValueError(f"Preset [{section}] has an invalid {key}.")


def _preset_chat_lines(source: IniDocument) -> tuple[str, ...]:
    """Extract and conservatively validate the preset's [ChatManager] body."""
    section_info = source.sections.get("chatmanager")
    if section_info is None:
        raise ValueError("Preset is missing its [ChatManager] section.")
    start, end, _display = section_info
    chat_lines: list[str] = []
    for line_index in range(start + 1, end):
        content = source.lines[line_index].rstrip("\r\n")
        stripped = content.strip()
        if not stripped or stripped.startswith((";", "#")):
            continue
        line_number = line_index + 1
        if len(content) >= 200 or "=" not in content:
            raise ValueError(
                f"Preset [ChatManager] has an invalid entry on line {line_number}."
            )
        key, value = content.split("=", 1)
        if not re.fullmatch(r"[A-Za-z0-9_.]+", key):
            raise ValueError(
                f"Preset [ChatManager] has an invalid key on line {line_number}."
            )
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(
                f"Preset [ChatManager] has an invalid value on line {line_number}."
            )
        chat_lines.append(content)
    if not chat_lines:
        raise ValueError("Preset [ChatManager] contains no chat settings.")
    return tuple(chat_lines)


def _preset_patch(source: IniDocument, *, expected_skin: str = SKIN_NAME) -> PresetLayout:
    sections: dict[str, dict[str, str]] = {}
    main = source.sections.get("main")
    if main is None or ("main", "uiskin") not in source.keys:
        raise ValueError("Preset is missing [Main] UISkin.")
    main_value = _raw_value(source.lines[source.keys[("main", "uiskin")]])
    _validate_source_value("UISkin", main_value, "Main", expected_skin=expected_skin)
    sections["Main"] = {"UISkin": main_value}
    for section in sorted(LAYOUT_GEOMETRY_SECTIONS, key=str.casefold):
        folded = section.casefold()
        if folded not in source.sections:
            raise ValueError(f"Preset is missing audited section [{section}].")
        values: dict[str, str] = {}
        version_index = source.keys.get((folded, "iniversion"))
        if version_index is not None:
            version = _raw_value(source.lines[version_index])
            _validate_source_value("INIVersion", version, section, expected_skin=expected_skin)
            values["INIVersion"] = version
        for key in LAYOUT_KEYS:
            line_index = source.keys.get((folded, key.casefold()))
            if line_index is None:
                continue
            value = _raw_value(source.lines[line_index])
            _validate_source_value(key, value, section, expected_skin=expected_skin)
            values[key] = value
        required = {"XRef", "YRef", "XPos", "YPos"}
        if not required.issubset(values):
            missing = ", ".join(sorted(required - values.keys()))
            raise ValueError(f"Preset [{section}] is missing required geometry: {missing}.")
        sections[section] = values
    return PresetLayout(sections=sections, chat_lines=_preset_chat_lines(source))


def _replace_ini_value(line: str, value: str) -> str:
    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    content = line[:-len(newline)] if newline else line
    before, after = content.split("=", 1)
    leading = after[:len(after) - len(after.lstrip(" \t"))]
    remainder = after[len(leading):]
    markers = [position for marker in ";#" if (position := remainder.find(marker)) >= 0]
    if markers:
        comment_start = min(markers)
        while comment_start > 0 and remainder[comment_start - 1] in " \t":
            comment_start -= 1
        suffix = remainder[comment_start:]
    else:
        suffix = remainder[len(remainder.rstrip(" \t")):]
    return f"{before}={leading}{value}{suffix}{newline}"


def _merge_ini_geometry(target: IniDocument, preset: PresetLayout) -> bytes:
    """Apply the preset's audited layout values and its [ChatManager] section."""
    lines = list(target.lines)
    insertions: dict[int, list[str]] = {}
    removed: set[int] = set()
    missing_sections: list[tuple[str, dict[str, str]]] = []
    for section, values in preset.sections.items():
        folded = section.casefold()
        section_info = target.sections.get(folded)
        if section_info is None:
            missing_sections.append((section, values))
            continue
        _start, end, _display = section_info
        for key in MERGE_KEY_ORDER:
            if key not in values:
                continue
            if key == "INIVersion":
                # Client schema versions belong to existing character data.
                # Source versions are used only for sections that do not yet exist.
                continue
            line_index = target.keys.get((folded, key.casefold()))
            if line_index is None:
                insertions.setdefault(end, []).append(f"{key}={values[key]}")
            else:
                lines[line_index] = _replace_ini_value(lines[line_index], values[key])
    chat_info = target.sections.get("chatmanager")
    if chat_info is not None:
        # ChatManager travels wholesale: the preset body replaces the target's.
        chat_start, chat_end, _chat_display = chat_info
        removed.update(range(chat_start + 1, chat_end))
        insertions.setdefault(chat_start + 1, []).extend(preset.chat_lines)

    output: list[str] = []
    for index in range(len(lines) + 1):
        if index in insertions:
            if output and not output[-1].endswith(("\n", "\r")):
                output[-1] += target.newline
            output.extend(value + target.newline for value in insertions[index])
        if index < len(lines) and index not in removed:
            output.append(lines[index])
    appended_blocks: list[tuple[str, list[str]]] = [
        (section, [f"{key}={values[key]}" for key in MERGE_KEY_ORDER if key in values])
        for section, values in missing_sections
    ]
    if chat_info is None:
        appended_blocks.append(("ChatManager", list(preset.chat_lines)))
    if appended_blocks:
        if output and not output[-1].endswith(("\n", "\r")):
            output[-1] += target.newline
        if output and output[-1].strip():
            output.append(target.newline)
        for block_index, (section, block_lines) in enumerate(appended_blocks):
            output.append(f"[{section}]{target.newline}")
            output.extend(f"{line}{target.newline}" for line in block_lines)
            if block_index + 1 < len(appended_blocks):
                output.append(target.newline)
    if output and not target.had_final_newline:
        output[-1] = output[-1].rstrip("\r\n")
    merged_text = "".join(output)
    return target.bom + merged_text.encode(target.encoding)


def _minimal_ini_from_patch(preset: PresetLayout, *,
                            newline: str = "\r\n") -> bytes:
    """Build a new target containing only the same audited merge boundary."""
    blocks: list[str] = []
    ordered_sections = ["Main"] + sorted(
        (section for section in preset.sections if section != "Main"), key=str.casefold
    )
    for section in ordered_sections:
        blocks.append(f"[{section}]")
        values = preset.sections[section]
        for key in MERGE_KEY_ORDER:
            if key in values:
                blocks.append(f"{key}={values[key]}")
        blocks.append("")
    blocks.append("[ChatManager]")
    blocks.extend(preset.chat_lines)
    blocks.append("")
    return newline.join(blocks).encode("utf-8")


def prepare_layout_update(source: Path, target: Path, *, allow_create: bool,
                          expected_skin: str = SKIN_NAME) -> LayoutUpdate:
    source_bytes = source.read_bytes()
    source_doc = _parse_ini(source_bytes, f"preset {source.name}")
    patch = _preset_patch(source_doc, expected_skin=expected_skin)
    if target.exists():
        if target.is_symlink():
            raise ValueError("Symbolic-link character layouts are not supported.")
        original = target.read_bytes()
        target_doc = _parse_ini(original, f"character layout {target.name}")
        updated = _merge_ini_geometry(target_doc, patch)
        return LayoutUpdate(target, original, updated, updated != original, False)
    if not allow_create:
        raise ValueError(
            "That character layout does not exist. Choose create target or log into the "
            "character once, close EverQuest, and run the installer again."
        )
    # New files use the identical audited boundary: layout values (geometry
    # plus visibility) for audited windows and the preset's [ChatManager].
    # Source-only lock, click-through, and other character settings never
    # leak in.
    return LayoutUpdate(
        target, None, _minimal_ini_from_patch(patch, newline=source_doc.newline),
        True, True,
    )


def _unique_backup_path(target: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = target.with_name(f"{target.name}.spinui-backup-{stamp}")
    candidate = base
    counter = 2
    while candidate.exists():
        candidate = target.with_name(f"{base.name}-{counter}")
        counter += 1
    return candidate


def _publish_new_target(staged: Path, target: Path) -> None:
    """Atomically publish without replacing a target that appeared mid-install."""
    if os.name == "nt":
        # Unlike os.replace, Windows os.rename fails when destination exists.
        os.rename(staged, target)
        return
    # Hard-link publication is same-filesystem, atomic, and no-replace on POSIX.
    os.link(staged, target)
    staged.unlink()


def commit_layout_update(update: LayoutUpdate) -> Path | None:
    """Atomically apply one prevalidated update and return its backup, if any."""
    if not update.changed:
        return None
    target = update.target
    target.parent.mkdir(parents=True, exist_ok=True)
    if update.original is None:
        if target.exists():
            raise RuntimeError(
                "The character layout appeared during installation; run the installer again "
                "so it can be merged safely."
            )
    else:
        try:
            current = target.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"Could not re-read {target.name}: {exc}") from exc
        if current != update.original:
            raise RuntimeError(
                f"{target.name} changed during installation; no layout changes were written."
            )

    temp_path: Path | None = None
    backup: Path | None = None
    backup_created = False
    try:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.spinui-", suffix=".tmp", dir=target.parent
        )
        temp_path = Path(temp_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(update.updated)
            stream.flush()
            os.fsync(stream.fileno())
        if update.original is not None:
            shutil.copystat(target, temp_path)
            backup = _unique_backup_path(target)
            backup_stream = backup.open("xb")
            backup_created = True
            with backup_stream as stream:
                stream.write(update.original)
                stream.flush()
                os.fsync(stream.fileno())
            shutil.copystat(target, backup)
            # Recheck after staging and backup creation so ordinary concurrent
            # edits fail closed instead of being silently replaced.
            if target.read_bytes() != update.original:
                raise RuntimeError(
                    f"{target.name} changed during installation; no layout changes were written."
                )
            os.replace(temp_path, target)
        else:
            _publish_new_target(temp_path, target)
        temp_path = None
        return backup
    except Exception:
        if backup is not None and backup_created:
            backup.unlink(missing_ok=True)
        raise
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def enable_windows_dpi_awareness() -> None:
    """Request crisp coordinates on modern Windows before Tk is created."""
    if os.name != "nt":
        return
    try:
        import ctypes
        # Per-monitor v2. Unsupported Windows builds simply fall through.
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError, TypeError):
        pass
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def character_layout_label(path: Path) -> str:
    """Return a friendly label while retaining the exact INI path internally."""
    match = re.fullmatch(
        r"UI_(?P<character>[^_]+)_(?P<server>.+)_LO(?P<loadout>\d+)\.ini",
        path.name,
        flags=re.IGNORECASE,
    )
    if not match:
        return path.name
    return (
        f"{match.group('character')}  ·  {match.group('server')}  ·  "
        f"Layout {int(match.group('loadout'))}"
    )


def resolve_layout_source(
        payload: Path, preset_key: str | None,
        resolution_profile: str = DEFAULT_RESOLUTION_PROFILE) -> Path:
    """Resolve an allowlisted preset, with the old top-level file as API fallback."""
    payload = payload.resolve()
    if preset_key is None:
        legacy = (payload / LAYOUT_NAME).resolve()
        if legacy.parent != payload:
            raise ValueError("The legacy layout source escaped the release payload.")
        if not legacy.is_file():
            raise FileNotFoundError(f"Release payload is missing {LAYOUT_NAME}.")
        return legacy
    if preset_key not in LAYOUT_PRESETS:
        raise ValueError(f"Unknown layout preset: {preset_key!r}.")
    if resolution_profile not in RESOLUTION_PROFILES:
        raise ValueError(
            f"Unknown resolution profile: {resolution_profile!r}.")
    layouts_root = (payload / "layouts").resolve()
    profile_root = (
        layouts_root / "profiles" / resolution_profile).resolve()
    if profile_root.parent.parent != layouts_root:
        raise ValueError("The selected profile escaped the release payload.")
    preset_root = (profile_root / preset_key).resolve()
    if preset_root.parent != profile_root:
        raise ValueError("The selected layout escaped its profile folder.")
    source = (preset_root / LAYOUT_NAME).resolve()
    if source.parent != preset_root:
        raise ValueError("The selected layout escaped its preset folder.")
    if not source.is_file():
        raise FileNotFoundError(
            "Release payload is missing "
            f"layouts\\profiles\\{resolution_profile}\\{preset_key}\\"
            f"{LAYOUT_NAME}."
        )
    return source


def validate_layout_target(eq_root: Path, target: Path | None, *,
                           allow_create: bool = False) -> Path:
    """Resolve a safe character INI, retaining an existing file's exact casing."""
    if target is None:
        raise ValueError("Choose a character layout before installing a preset.")
    eq_root = eq_root.resolve()
    if any(part in {".", ".."} for part in target.parts):
        raise ValueError("Character layout paths cannot contain traversal segments.")
    candidate = target if target.is_absolute() else eq_root / target
    if candidate.parent.resolve() != eq_root:
        raise ValueError("The character layout must be an INI in the EverQuest folder.")
    if not re.fullmatch(r"UI_[^_]+_.+_LO\d+\.ini", candidate.name, flags=re.IGNORECASE):
        raise ValueError("Select an existing UI_<Character>_<server>_LO#.ini file.")
    existing = next(
        (path for path in character_layouts(eq_root)
         if path.name.casefold() == candidate.name.casefold()),
        None,
    )
    if existing is not None:
        if existing.is_symlink() or existing.resolve().parent != eq_root:
            raise ValueError("Linked character layouts are not supported.")
        return existing.resolve()
    if not allow_create:
        raise ValueError(
            "That character layout does not exist. Log into the character once, "
            "close EverQuest, and run the installer again."
        )
    return candidate.resolve()


def layout_review(
        choice: str, target: Path | None,
        resolution_profile: str = DEFAULT_RESOLUTION_PROFILE) -> tuple[str, str]:
    """Pure review copy shared by the wizard and its selftest."""
    if choice == KEEP_LAYOUT:
        return "KEEP EXISTING", "No character INI will be changed."
    preset = LAYOUT_PRESETS.get(choice)
    if preset is None:
        raise ValueError(f"Unknown layout preset: {choice!r}.")
    if resolution_profile not in RESOLUTION_PROFILES:
        raise ValueError(
            f"Unknown resolution profile: {resolution_profile!r}.")
    target_text = target.name if target is not None else "Choose a character layout"
    profile = RESOLUTION_PROFILES[resolution_profile]
    return (
        f"{preset.title} · {profile.width}×{profile.height}",
        f"Apply to {target_text}; each changed merge gets a timestamped backup.",
    )


def release_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_eq_root(path: Path) -> bool:
    return path.is_dir() and (path / "eqgame.exe").is_file()


def find_linux_loremaster_artifact(payload: Path) -> Path | None:
    """Locate the native Linux Loremaster build in the release payload, if any.

    Returns None when absent (a common case: the artifact is only produced by
    CI, so a source checkout won't have one) rather than raising, since the
    caller must still be able to install the skin on its own.
    """
    matches = sorted(payload.glob(LOREMASTER_LINUX_ARTIFACT_GLOB))
    return matches[0] if matches else None


def _linux_loremaster_skip_detail(payload: Path) -> str:
    """Explain why no native Loremaster was installed, and what to do instead.

    A tar.gz-only payload is a distinct and recoverable situation: the Linux
    build is present, it just is not the single-file form the installer can
    place. Saying so beats implying nothing was downloaded.
    """
    tarballs = sorted(payload.glob(LOREMASTER_LINUX_TARBALL_GLOB))
    if tarballs:
        return (
            f"found {tarballs[0].name}, but only "
            f"{LOREMASTER_LINUX_ARTIFACT_GLOB} can be installed automatically. "
            "Extract that archive and run its ./loremaster binary directly."
        )
    return (
        f"no native Linux build ({LOREMASTER_LINUX_ARTIFACT_GLOB}) was found in "
        "the release payload. Download the Linux Loremaster build from the "
        "releases page and run the installer again to install it."
    )


def detect_client_resolution(eq_root: Path) -> tuple[int, int] | None:
    """Best-effort read of the client's display resolution from eqclient.ini.

    Read-only: the installer never writes eqclient.ini. Key names vary across
    client generations, so any key containing width/xres (and height/yres)
    with a plausible pixel value counts; fullscreen keys outrank windowed
    ones, and the largest plausible pair wins within a rank.
    """
    ini = eq_root / "eqclient.ini"
    try:
        text = ini.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    widths: list[tuple[int, int]] = []
    heights: list[tuple[int, int]] = []
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, raw = line.partition("=")
        key = key.strip().lower()
        try:
            value = int(raw.strip())
        except ValueError:
            continue
        rank = 1 if "fullscreen" in key else 0
        if ("width" in key or "xres" in key) and 640 <= value <= 7680:
            widths.append((rank, value))
        elif ("height" in key or "yres" in key) and 480 <= value <= 4320:
            heights.append((rank, value))
    if not widths or not heights:
        return None
    return max(widths)[1], max(heights)[1]


def recommended_resolution_profile(
        resolution: tuple[int, int] | None) -> ResolutionProfile:
    if resolution is None:
        return RESOLUTION_PROFILES[DEFAULT_RESOLUTION_PROFILE]
    width, height = resolution
    exact = RESOLUTION_PROFILES.get(f"{width}x{height}")
    if exact is not None:
        return exact
    aspect = width / max(1, height)

    def score(profile: ResolutionProfile) -> float:
        profile_aspect = profile.width / profile.height
        return (
            abs(aspect - profile_aspect) * 3
            + abs(height - profile.height) / max(height, profile.height) * 2
            + abs(width - profile.width) / max(width, profile.width)
        )

    return min(RESOLUTION_PROFILES.values(), key=score)


def resolution_note(resolution: tuple[int, int] | None) -> str:
    """Layout-page guidance for the detected display."""
    if resolution is None:
        return (
            "Display not detected — choose the screen profile that matches "
            "the resolution used by EverQuest."
        )
    width, height = resolution
    profile = recommended_resolution_profile(resolution)
    if (width, height) == (profile.width, profile.height):
        return (
            f"{width}×{height} detected — an exact, overlap-validated SpinUI "
            "profile is ready and selected below."
        )
    return (
        f"{width}×{height} detected — {profile.label} is the closest validated "
        "profile; you can choose another before installing."
    )


def _steam_libraries_from_roots(roots: list[Path]) -> list[Path]:
    libraries: list[Path] = []
    for steam in roots:
        if not steam.is_dir():
            continue
        libraries.append(steam)
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for raw in re.findall(r'"path"\s+"([^"]+)"', text):
            libraries.append(Path(raw.replace("\\\\", "\\")))
    return libraries


def steam_libraries() -> list[Path]:
    return _steam_libraries_from_roots([
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Steam",
    ])


# Wine/Proton EQ folder shapes probed inside each detected prefix's drive_c,
# mirroring the native Windows candidates in find_eq_roots() (minus the
# drive letter, which drive_c stands in for).
WINE_EQ_RELATIVE_ROOTS: tuple[tuple[str, ...], ...] = (
    ("EQLegends",),
    ("Users", "Public", "Daybreak Game Company", "Installed Games", "EverQuest Legends"),
    ("Users", "Public", "Daybreak Game Company", "Installed Games", "EverQuest"),
    ("Program Files (x86)", "Sony", "EverQuest"),
)
WINE_STEAM_ROOTS: tuple[tuple[str, ...], ...] = (
    ("Program Files (x86)", "Steam"),
    ("Program Files", "Steam"),
)


def wine_prefixes() -> list[Path]:
    """Wine/Proton prefixes that might hold a Windows EverQuest install.

    Every glob here is a single, fixed-depth listing (never recursive), and
    every directory read is wrapped so an unreadable or half-provisioned
    Steam/Lutris tree is skipped instead of raising during auto-detection.
    """
    home = Path.home()
    candidates: list[Path] = []
    env_prefix = os.environ.get("WINEPREFIX")
    if env_prefix:
        candidates.append(Path(env_prefix))
    candidates.append(home / ".wine")

    compatdata_roots = [
        home / ".steam" / "steam" / "steamapps" / "compatdata",
        home / ".local" / "share" / "Steam" / "steamapps" / "compatdata",
        (home / ".var" / "app" / "com.valvesoftware.Steam" / "data"
         / "Steam" / "steamapps" / "compatdata"),
        (home / ".var" / "app" / "com.valvesoftware.Steam" / ".local"
         / "share" / "Steam" / "steamapps" / "compatdata"),
    ]
    for compatdata in compatdata_roots:
        try:
            if not compatdata.is_dir():
                continue
            entries = sorted(compatdata.iterdir())
        except OSError:
            continue
        candidates.extend(entry / "pfx" for entry in entries)

    lutris_root = home / "Games"
    try:
        if lutris_root.is_dir():
            candidates.extend(sorted(lutris_root.iterdir()))
    except OSError:
        pass

    seen: set[str] = set()
    prefixes: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if (candidate / "drive_c").is_dir():
                prefixes.append(candidate)
        except OSError:
            continue
    return prefixes


def find_wine_eq_roots() -> list[Path]:
    """Probe every detected Wine/Proton prefix for an EQ install.

    Uses the same eqgame.exe-presence check as native discovery, applied to
    the same folder shapes plus the prefix's own Steam library, if any.
    """
    found: list[Path] = []
    seen: set[str] = set()
    for prefix in wine_prefixes():
        drive_c = prefix / "drive_c"
        candidates = [drive_c.joinpath(*parts) for parts in WINE_EQ_RELATIVE_ROOTS]
        for steam_parts in WINE_STEAM_ROOTS:
            for library in _steam_libraries_from_roots([drive_c.joinpath(*steam_parts)]):
                candidates.extend([
                    library / "steamapps" / "common" / "EverQuest",
                    library / "steamapps" / "common" / "EverQuest Legends",
                ])
        for candidate in candidates:
            key = str(candidate).lower()
            if key in seen:
                continue
            if is_eq_root(candidate):
                seen.add(key)
                found.append(candidate)
    return found


def find_eq_roots() -> list[Path]:
    candidates = [
        Path(r"C:\EQLegends"),
        Path(r"D:\EQLegends"),
        Path(r"C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest Legends"),
        Path(r"C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest"),
        Path(r"C:\Program Files (x86)\Sony\EverQuest"),
        Path.home() / "EverQuest Legends",
    ]
    for library in steam_libraries():
        candidates.extend([
            library / "steamapps" / "common" / "EverQuest",
            library / "steamapps" / "common" / "EverQuest Legends",
        ])
    found: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).lower()
        if key not in seen and is_eq_root(path):
            seen.add(key)
            found.append(path)
    # Wine/Proton prefixes are additive: they never replace or shadow a
    # native Windows install found above.
    for path in find_wine_eq_roots():
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            found.append(path)
    return found


def character_layouts(eq_root: Path) -> list[Path]:
    return sorted(eq_root.glob("UI_*_*_LO*.ini"), key=lambda p: p.name.lower())


def local_app_data(override: Path | None = None) -> Path:
    if override is not None:
        return override
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SpinsLoremaster"
    # XDG Base Directory spec: $XDG_DATA_HOME, defaulting to ~/.local/share.
    # Never fall back to an %APPDATA%-shaped path on Linux.
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "SpinsLoremaster"


def startup_folder(override: Path | None = None) -> Path:
    if override is not None:
        return override
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", Path.home()))
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    # XDG Autostart spec: $XDG_CONFIG_HOME/autostart, defaulting to ~/.config.
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return base / "autostart"


def desktop_folder(override: Path | None = None) -> Path:
    if override is not None:
        return override
    if os.name == "nt":
        try:
            import ctypes
            buffer = ctypes.create_unicode_buffer(260)
            # CSIDL_DESKTOPDIRECTORY follows redirected/OneDrive desktops.
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0:
                return Path(buffer.value)
        except (AttributeError, OSError):
            pass
    return Path.home() / "Desktop"


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def _write_shortcut(executable: Path, shortcut: Path, *, arguments: str,
                    description: str) -> None:
    if os.name != "nt":
        raise RuntimeError("Windows shortcuts can only be created on Windows")
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$w=New-Object -ComObject WScript.Shell;"
        f"$s=$w.CreateShortcut('{_ps_quote(str(shortcut))}');"
        f"$s.TargetPath='{_ps_quote(str(executable))}';"
        f"$s.Arguments='{_ps_quote(arguments)}';"
        f"$s.WorkingDirectory='{_ps_quote(str(executable.parent))}';"
        f"$s.Description='{_ps_quote(description)}';"
        f"$s.IconLocation='{_ps_quote(str(executable))},0';"
        "$s.Save()"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Could not create {shortcut.name}: {detail}")


def _write_desktop_entry(executable: Path, shortcut: Path, *, arguments: str,
                         description: str) -> None:
    """Write a freedesktop .desktop entry that launches a native Linux binary.

    ``executable`` must already be a directly runnable Linux executable (the
    installed Loremaster AppImage, chmod +x'd by the caller) — never a
    Windows PE. There is deliberately no interpreter/wine prefix here:
    Loremaster is a native Linux (Electron) build on this platform, and is
    never installed or launched under Wine.
    """
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    exec_command = shlex.quote(str(executable))
    if arguments:
        exec_command += f" {arguments}"
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={description}\n"
        f"Exec={exec_command}\n"
        f"Path={shlex.quote(str(executable.parent))}\n"
        "Terminal=false\n"
        "Categories=Game;\n"
    )
    # Stage-then-rename so a reader never observes a half-written entry, and
    # set the executable bit up front since most launchers require it before
    # trusting a freshly dropped .desktop file.
    descriptor, temp_name = tempfile.mkstemp(
        prefix=".spinui-shortcut-", suffix=".desktop", dir=shortcut.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        temp_path.chmod(0o755)
        os.replace(temp_path, shortcut)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def set_startup_shortcut(executable: Path, enabled: bool,
                         folder: Path | None = None) -> None:
    shortcut = startup_folder(folder) / STARTUP_LINK
    if not enabled:
        shortcut.unlink(missing_ok=True)
        return
    if os.name == "nt":
        _write_shortcut(
            executable, shortcut, arguments="--wait-for-eq",
            description="Wait for EverQuest, then open Spin's Loremaster",
        )
    else:
        _write_desktop_entry(
            executable, shortcut, arguments="--wait-for-eq",
            description="Wait for EverQuest, then open Spin's Loremaster",
        )


def set_desktop_shortcut(executable: Path, enabled: bool,
                         folder: Path | None = None) -> None:
    shortcut = desktop_folder(folder) / DESKTOP_LINK
    if not enabled:
        shortcut.unlink(missing_ok=True)
        return
    if os.name == "nt":
        _write_shortcut(
            executable, shortcut, arguments="",
            description="Open Spin's Loremaster",
        )
    else:
        _write_desktop_entry(
            executable, shortcut, arguments="",
            description="Open Spin's Loremaster",
        )


def _linux_process_pids(image_name: str, *, proc_root: Path = Path("/proc")) -> list[int]:
    """Return the pids of every running process named image_name.

    Under Wine, eqgame.exe runs as a real Linux process whose /proc/<pid>/comm
    is set (via prctl) to the Windows executable's basename, so this needs no
    Wine-specific API; the same scan also finds a native Linux process like
    Loremaster's (comm "loremaster"). cmdline is checked too since comm
    truncates at 15 bytes and some loaders leave comm as their own name.
    """
    target = image_name.casefold()
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return []
    pids: list[int] = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if comm.casefold() == target:
            pids.append(int(entry.name))
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        # Wine cmdline arguments may carry Windows-style backslash paths
        # (e.g. Z:\EQLegends\eqgame.exe), which POSIX Path() would not split
        # on, so both separators are checked explicitly.
        for part in cmdline.split(b"\x00"):
            if not part:
                continue
            basename = re.split(r"[\\/]", part.decode(errors="replace"))[-1]
            if basename.casefold() == target:
                pids.append(int(entry.name))
                break
    return pids


def _linux_process_running(image_name: str, *, proc_root: Path = Path("/proc")) -> bool:
    return bool(_linux_process_pids(image_name, proc_root=proc_root))


def _linux_signal_processes(image_name: str, sig: int) -> bool:
    """Send sig to every running process named image_name.

    Returns whether any matching process existed. There is no tasklist/
    taskkill equivalent on Linux, so /proc is scanned directly and each pid
    is signaled with os.kill; a pid that exits mid-scan is not an error.
    """
    pids = _linux_process_pids(image_name)
    for pid in pids:
        try:
            os.kill(pid, sig)
        except OSError:
            continue
    return bool(pids)


def process_is_running(image_name: str) -> bool:
    if os.name != "nt":
        return _linux_process_running(image_name)
    try:
        result = subprocess.run(
            ["tasklist.exe", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
            capture_output=True, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    return result.returncode == 0 and image_name.lower() in result.stdout.lower()


def stop_running_loremaster(image_name: str = LOREMASTER_NAME) -> bool:
    """Close an installed Loremaster so its executable can be updated.

    image_name is LOREMASTER_NAME ("Loremaster.exe") on Windows, or the
    native Linux build's process name (LOREMASTER_LINUX_PROCESS_NAME,
    "loremaster") on Linux -- the caller picks based on os.name since the
    two platforms install entirely different artifacts under this app data
    directory.
    """
    if not process_is_running(image_name):
        return False
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(["taskkill.exe", "/IM", image_name],
                       capture_output=True, creationflags=flags)
        for _ in range(10):
            if not process_is_running(image_name):
                return True
            time.sleep(0.1)
        subprocess.run(["taskkill.exe", "/F", "/IM", image_name],
                       capture_output=True, creationflags=flags)
        for _ in range(10):
            if not process_is_running(image_name):
                return True
            time.sleep(0.1)
        raise RuntimeError(f"Close {image_name} and run the installer again so it can be updated.")
    # Linux: there is no tasklist/taskkill equivalent, so /proc is scanned
    # directly (see _linux_signal_processes) and each matching pid is
    # signaled -- SIGTERM first, then SIGKILL if it ignores that.
    _linux_signal_processes(image_name, signal.SIGTERM)
    for _ in range(10):
        if not process_is_running(image_name):
            return True
        time.sleep(0.1)
    _linux_signal_processes(image_name, signal.SIGKILL)
    for _ in range(10):
        if not process_is_running(image_name):
            return True
        time.sleep(0.1)
    raise RuntimeError(f"Close {image_name} and run the installer again so it can be updated.")


def configure_loremaster(eq_root: Path, app_dir: Path) -> None:
    config = app_dir / "loremaster_config.json"
    try:
        decoded = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
        data = decoded if isinstance(decoded, dict) else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data["log_dir"] = str(eq_root)
    config.write_text(json.dumps(data, indent=2), encoding="utf-8")


def replace_tree(source: Path, destination: Path) -> bool:
    """Install an exact directory copy, restoring the old tree on failure."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    updating = destination.exists()
    with tempfile.TemporaryDirectory(
            prefix=f".{destination.name}-install-", dir=destination.parent,
            ignore_cleanup_errors=True) as temp_name:
        temp_root = Path(temp_name)
        staged = temp_root / "fresh"
        previous = temp_root / "previous"
        shutil.copytree(source, staged)
        if updating:
            os.replace(destination, previous)
        try:
            os.replace(staged, destination)
        except Exception:
            if updating and previous.exists() and not destination.exists():
                os.replace(previous, destination)
            raise
    return updating


def install_payload(payload: Path, eq_root: Path, *, install_layout: bool,
                    layout_target: Path | None, run_at_startup: bool,
                    desktop_shortcut: bool = True,
                    app_dir: Path | None = None,
                    startup_dir: Path | None = None,
                    desktop_dir: Path | None = None,
                    replace_running: bool = False,
                    require_eq_closed: bool = False,
                    layout_preset: str | None = None,
                    resolution_profile: str = DEFAULT_RESOLUTION_PROFILE,
                    create_layout_target: bool = False,
                    skin_name: str = SKIN_NAME) -> list[str]:
    payload = payload.resolve()
    eq_root = eq_root.resolve()
    if not is_eq_root(eq_root):
        raise ValueError("Choose the EverQuest folder that contains eqgame.exe.")
    if skin_name not in AVAILABLE_SKINS:
        raise ValueError(f"Unknown skin: {skin_name!r}.")
    skin_source = payload / skin_name
    # Windows always requires Loremaster.exe (unchanged, existing behavior).
    # Linux has no fixed filename -- the release version is embedded in it --
    # and, unlike the skin, the native build is only produced by CI, so a
    # source checkout commonly won't have one; that is not fatal, only the
    # Loremaster step is skipped (see below).
    lore_source: Path | None = (
        payload / LOREMASTER_NAME if os.name == "nt"
        else find_linux_loremaster_artifact(payload)
    )
    lore_process_name = LOREMASTER_NAME if os.name == "nt" else LOREMASTER_LINUX_PROCESS_NAME
    layout_source: Path | None = None
    target: Path | None = None
    layout_update: LayoutUpdate | None = None
    if install_layout:
        if resolution_profile not in RESOLUTION_PROFILES:
            raise ValueError(
                f"Unknown resolution profile: {resolution_profile!r}.")
        # Validate both paths before changing the skin or Loremaster. The
        # installer must never report a partial success for an invalid choice.
        layout_source = resolve_layout_source(
            payload, layout_preset, resolution_profile)
        target = validate_layout_target(
            eq_root, layout_target, allow_create=create_layout_target
        )
        layout_update = prepare_layout_update(
            layout_source, target, allow_create=create_layout_target,
            expected_skin=skin_name,
        )
    if not skin_source.is_dir():
        raise FileNotFoundError(f"Release payload is missing {skin_name}.")
    if os.name == "nt" and not lore_source.is_file():
        raise FileNotFoundError(f"Release payload is missing {LOREMASTER_NAME}.")
    if require_eq_closed and process_is_running("eqgame.exe"):
        raise RuntimeError(
            "EverQuest is running. Camp out and close eqgame.exe before updating "
            "SpinUI so the client cannot overwrite the installed files."
        )
    stopped_loremaster = (
        stop_running_loremaster(lore_process_name)
        if replace_running and lore_source is not None else False
    )

    results: list[str] = []
    skin_destination = eq_root / "uifiles" / skin_name
    # Use a staged directory swap so removed/renamed files from an older build
    # cannot survive the update and interfere with EQ's skin loader. The skin
    # is independent of Loremaster below, and must fully succeed even when
    # Loremaster is skipped.
    updating_skin = replace_tree(skin_source, skin_destination)
    results.append(
        f"{'Updated' if updating_skin else 'Installed'} {skin_name} at {skin_destination}"
    )

    lore_destination_dir = local_app_data(app_dir)
    lore_destination: Path | None = None
    if lore_source is not None:
        lore_destination_dir.mkdir(parents=True, exist_ok=True)
        destination_name = LOREMASTER_NAME if os.name == "nt" else LOREMASTER_LINUX_DESTINATION_NAME
        lore_destination = lore_destination_dir / destination_name
        updating_loremaster = lore_destination.exists()
        staged_loremaster = lore_destination.with_suffix(".installing")
        try:
            shutil.copy2(lore_source, staged_loremaster)
            if os.name != "nt":
                staged_loremaster.chmod(0o755)
            os.replace(staged_loremaster, lore_destination)
        finally:
            staged_loremaster.unlink(missing_ok=True)
        configure_loremaster(eq_root, lore_destination_dir)
        results.append(
            f"{'Updated' if updating_loremaster else 'Installed'} Loremaster at {lore_destination}"
        )
        if stopped_loremaster:
            results.append("Closed the previous Loremaster build before updating")
    else:
        results.append(
            "Skipped Loremaster: " + _linux_loremaster_skip_detail(payload)
        )

    if install_layout:
        assert layout_source is not None and target is not None and layout_update is not None
        backup = commit_layout_update(layout_update)
        preset_name = (
            LAYOUT_PRESETS[layout_preset].title.title()
            if layout_preset in LAYOUT_PRESETS else "Ultrawide"
        )
        profile_name = RESOLUTION_PROFILES[resolution_profile].label
        if not layout_update.changed:
            results.append(
                f"The {preset_name} · {profile_name} layout already matched "
                f"{target.name}")
        elif layout_update.created:
            results.append(
                f"Created {target.name} with the {preset_name} · "
                f"{profile_name} layout")
        else:
            results.append(
                f"Applied the {preset_name} · {profile_name} layout "
                f"(windows, visibility, chat routing) to {target.name}"
            )
        if backup is not None:
            results.append(f"Backed up the previous INI to {backup.name}")
    else:
        results.append("Kept the existing character layout unchanged")

    if lore_destination is not None:
        set_startup_shortcut(lore_destination, run_at_startup, startup_dir)
        results.append("Loremaster startup enabled" if run_at_startup
                       else "Loremaster startup disabled")
        set_desktop_shortcut(lore_destination, desktop_shortcut, desktop_dir)
        results.append("Loremaster desktop shortcut created" if desktop_shortcut
                       else "Loremaster desktop shortcut skipped")
    else:
        # Nothing was installed to point a shortcut at. Still clear any
        # stale shortcut left over from a previous install where Loremaster
        # was present, rather than leaving it dangling.
        placeholder = lore_destination_dir / "Loremaster"
        set_startup_shortcut(placeholder, False, startup_dir)
        set_desktop_shortcut(placeholder, False, desktop_dir)
        if run_at_startup or desktop_shortcut:
            results.append("Loremaster shortcuts skipped: Loremaster was not installed")
    return results


def selftest() -> int:
    def expect_error(error_type, action) -> Exception:
        try:
            action()
        except error_type as exc:
            return exc
        raise AssertionError(f"expected {error_type.__name__}")

    def preset_bytes(
            preset_key: str, profile_key: str = DEFAULT_RESOLUTION_PROFILE,
            *, newline: str = "\n") -> bytes:
        profile_offset = (
            0 if profile_key == DEFAULT_RESOLUTION_PROFILE
            else (list(RESOLUTION_PROFILES).index(profile_key) + 1) * 5
        )
        offset = profile_offset + list(LAYOUT_PRESETS).index(preset_key) * 100
        lines = ["[Main]", f"UISkin={SKIN_NAME}", "SourceOnly=must-not-leak"]
        for index, section in enumerate(sorted(LAYOUT_GEOMETRY_SECTIONS, key=str.casefold)):
            lines.extend([
                "", f"[{section}]",
                f"INIVersion={2 if section == 'HotButtonWnd' else 1}",
                "XRef=left", "YRef=top",
                f"XPos={offset + index}.125000%", f"YPos=-{index}.250000%",
                f"Width={300 + index}", f"Height={100 + index}",
                "Show=1", "Alpha=111", "FadeToAlpha=190", "Fades=1", "Locked=1",
            ])
        lines.extend(["", "[ChatManager]", "ChannelMap0=99", "ChatWindow0_Name=SOURCE"])
        return (newline.join(lines) + newline).encode("utf-8")

    generator_path = release_root() / "tools" / "generate_spinui_layout.py"
    if generator_path.is_file():
        import runpy
        generator_sections = set(runpy.run_path(str(generator_path))["PLACEMENTS"])
        generator_sections.add("EQMainWnd")
        assert generator_sections == set(LAYOUT_GEOMETRY_SECTIONS), (
            "installer geometry manifest drifted from generate_spinui_layout.py"
        )
    assert _replace_ini_value("XPos=1%;keep me\r\n", "2%") == "XPos=2%;keep me\r\n"
    assert _replace_ini_value("XPos=1%  # keep me\n", "2%") == "XPos=2%  # keep me\n"

    with tempfile.TemporaryDirectory() as td:
        eq = Path(td)
        assert detect_client_resolution(eq) is None
        (eq / "eqclient.ini").write_text(
            "[Defaults]\nWindowedWidth=1720\nWindowedHeight=720\n"
            "FullscreenWidth=3440\nFullscreenHeight=1440\nBitsPerPixel=32\n",
            encoding="utf-8")
        assert detect_client_resolution(eq) == (3440, 1440)
        (eq / "eqclient.ini").write_text(
            "[Defaults]\nXRes=3840\nYRes=2160\n", encoding="utf-8")
        assert detect_client_resolution(eq) == (3840, 2160)
        (eq / "eqclient.ini").write_text(
            "[Defaults]\nWidth=notanumber\nSoundVolume=100\n", encoding="utf-8")
        assert detect_client_resolution(eq) is None
    assert "exact" in resolution_note((3440, 1440))
    assert "exact" in resolution_note((3840, 2160))
    assert "exact" in resolution_note((2560, 1440))
    assert "exact" in resolution_note((1920, 1080))
    assert recommended_resolution_profile((2048, 1080)).key == "2048x1080"
    assert "closest" in resolution_note((1920, 1200))
    assert "not detected" in resolution_note(None)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        payload = root / "payload"
        eq = root / "EverQuest Legends"
        app = root / "appdata"
        startup = root / "startup"
        desktop = root / "desktop"
        (payload / SKIN_NAME).mkdir(parents=True)
        (payload / SKIN_NAME / "EQUI.xml").write_text("<xml/>", encoding="utf-8")
        (payload / LOREMASTER_NAME).write_bytes(b"loremaster")
        # Present regardless of OS: only os.name == "nt" ever reads LOREMASTER_NAME,
        # and only non-nt ever globs for the AppImage, so each platform's
        # selftest run exercises exactly the artifact it would really use.
        (payload / "Loremaster-9.9.9-x64.AppImage").write_bytes(b"loremaster")
        (payload / LAYOUT_NAME).write_bytes(preset_bytes("combat-focus"))
        for preset_key in LAYOUT_PRESETS:
            preset_dir = payload / "layouts" / preset_key
            preset_dir.mkdir(parents=True)
            (preset_dir / LAYOUT_NAME).write_bytes(preset_bytes(preset_key))
        for profile_key in RESOLUTION_PROFILES:
            for preset_key in LAYOUT_PRESETS:
                preset_dir = (
                    payload / "layouts" / "profiles"
                    / profile_key / preset_key)
                preset_dir.mkdir(parents=True)
                (preset_dir / LAYOUT_NAME).write_bytes(
                    preset_bytes(preset_key, profile_key))
        eq.mkdir()
        (eq / "eqgame.exe").write_bytes(b"")
        installed_skin = eq / "uifiles" / SKIN_NAME
        installed_skin.mkdir(parents=True)
        (installed_skin / "EQUI.xml").write_text("old skin", encoding="utf-8")
        (installed_skin / "removed-in-new-build.tga").write_bytes(b"stale")
        app.mkdir()
        (app / LOREMASTER_NAME).write_bytes(b"old loremaster")
        (app / LOREMASTER_LINUX_DESTINATION_NAME).write_bytes(b"old loremaster")
        (app / "loremaster_config.json").write_text(
            json.dumps({"mini_mode": False}), encoding="utf-8"
        )
        sentinel = (
            b"\xef\xbb\xbf; caf\xc3\xa9 and comments survive\r\n"
            b"[Main]\r\nUISkin=old_skin\r\nKeepMain=sentinel\r\n"
            b"[MainChat]\r\nXRef=right\r\nYRef=bottom\r\nXPos=9.5%\r\n"
            b"YPos=8.5%\r\nWidth=50\r\nHeight=60\r\nAlpha=222\r\nShow=0\r\n"
            b"Locked=0\r\nCustomWindowKey=keep\r\n"
            b"[HotButtonWnd]\r\nXRef=left\r\nYRef=top\r\nXPos=1%\r\nYPos=2%\r\n"
            b"ShowKeyMap=1\r\nButtonSentinel=keep\r\n"
            b"[MapViewWnd]\r\nXRef=left\r\nYRef=top\r\nXPos=2%\r\nYPos=3%\r\n"
            b"MapFilter=keep\r\nColumnSort=keep\r\n"
            b"[ChatManager]\r\nChannelMap0=7\r\nHitMode0=42\r\n"
            b"ChatWindow0_Name=My Private Routing\r\n"
            b"[UnknownClientSection]\r\nMystery=100%\r\nNoFinalNewline=keep"
        )
        client_added = b"".join(
            f"[ClientAdded{index}]\r\nValue{index}=keep-{index}\r\n".encode()
            for index in range(14)
        )
        sentinel = sentinel.replace(b"[UnknownClientSection]", client_added + b"[UnknownClientSection]")
        target = eq / "UI_Test_qeynos_LO1.ini"
        target.write_bytes(sentinel)
        sibling = eq / "Test_qeynos_LO1.ini"
        sibling.write_bytes(b"[HotButtons]\r\nPage1Button1=do-not-touch\r\n")
        eqclient = eq / "eqclient.ini"
        eqclient.write_bytes(b"ClientSentinel=keep\r\n")
        sibling_stat = sibling.stat().st_mtime_ns
        eqclient_stat = eqclient.stat().st_mtime_ns

        result = install_payload(
            payload, eq, install_layout=True, layout_target=target,
            run_at_startup=False, desktop_shortcut=False, app_dir=app,
            startup_dir=startup, desktop_dir=desktop,
            layout_preset="combat-focus",
        )
        assert result
        assert (installed_skin / "EQUI.xml").read_text(encoding="utf-8") == "<xml/>"
        assert not (installed_skin / "removed-in-new-build.tga").exists()
        if os.name == "nt":
            assert (app / LOREMASTER_NAME).read_bytes() == b"loremaster"
        else:
            assert (app / LOREMASTER_LINUX_DESTINATION_NAME).read_bytes() == b"loremaster"
            assert os.access(app / LOREMASTER_LINUX_DESTINATION_NAME, os.X_OK)
            assert any("Skipped Loremaster" not in line for line in result)
        merged = target.read_bytes()
        assert merged.startswith(b"\xef\xbb\xbf")
        assert b"\n" not in merged.replace(b"\r\n", b"")
        assert not merged.endswith((b"\r", b"\n"))
        for protected in (
            b"; caf\xc3\xa9 and comments survive\r\n",
            b"KeepMain=sentinel\r\n",
            b"Locked=0\r\n", b"CustomWindowKey=keep\r\n",
            b"ShowKeyMap=1\r\n", b"ButtonSentinel=keep\r\n",
            b"MapFilter=keep\r\n", b"ColumnSort=keep\r\n",
            b"[UnknownClientSection]\r\n", b"Mystery=100%\r\n",
            b"NoFinalNewline=keep",
        ):
            assert protected in merged, protected
        for index in range(14):
            assert f"[ClientAdded{index}]\r\nValue{index}=keep-{index}\r\n".encode() in merged
        assert b"UISkin=spinui_reloaded\r\n" in merged
        mainchat_index = sorted(LAYOUT_GEOMETRY_SECTIONS, key=str.casefold).index("MainChat")
        assert f"XPos={mainchat_index}.125000%\r\n".encode() in merged
        mainchat_block = re.search(
            rb"\[MainChat\]\r\n(.*?)(?=\[HotButtonWnd\]\r\n)",
            merged, flags=re.DOTALL,
        )
        assert mainchat_block and b"INIVersion" not in mainchat_block.group(1)
        # Preset visibility overrides the target's stale Show/Alpha values.
        assert b"Show=1\r\n" in mainchat_block.group(1)
        assert b"Alpha=111\r\n" in mainchat_block.group(1)
        assert b"FadeToAlpha=190\r\n" in mainchat_block.group(1)
        assert b"Fades=1\r\n" in mainchat_block.group(1)
        assert b"Alpha=222" not in merged and b"Show=0\r\n" not in merged
        hotbutton_block = re.search(
            rb"\[HotButtonWnd\]\r\n(.*?)(?=\[MapViewWnd\]\r\n)",
            merged, flags=re.DOTALL,
        )
        assert hotbutton_block and b"INIVersion" not in hotbutton_block.group(1)
        assert b"[AggroMeterWnd]\r\nINIVersion=1\r\n" in merged
        # The preset's ChatManager replaces the target's, byte for byte.
        chat_block = re.search(
            rb"\[ChatManager\]\r\n(.*?)(?=\[ClientAdded0\]\r\n)",
            merged, flags=re.DOTALL,
        )
        assert chat_block is not None
        assert chat_block.group(1) == b"ChannelMap0=99\r\nChatWindow0_Name=SOURCE\r\n"
        assert b"ChannelMap0=7\r\n" not in merged and b"HitMode0=42" not in merged
        assert b"My Private Routing" not in merged
        backups = list(eq.glob(f"{target.name}.spinui-backup-*"))
        assert len(backups) == 1 and backups[0].read_bytes() == sentinel
        assert sibling.read_bytes() == b"[HotButtons]\r\nPage1Button1=do-not-touch\r\n"
        assert sibling.stat().st_mtime_ns == sibling_stat
        assert eqclient.read_bytes() == b"ClientSentinel=keep\r\n"
        assert eqclient.stat().st_mtime_ns == eqclient_stat
        config = json.loads((app / "loremaster_config.json").read_text())
        assert config["log_dir"] == str(eq.resolve())
        assert config["mini_mode"] is False
        assert not (startup / STARTUP_LINK).exists()
        assert not (desktop / DESKTOP_LINK).exists()

        # Reapplying the same preset is byte/mtime-idempotent and creates no backup.
        merged_stat = target.stat().st_mtime_ns
        install_payload(
            payload, eq, install_layout=True, layout_target=target,
            layout_preset="combat-focus", run_at_startup=False,
            desktop_shortcut=False, app_dir=app,
            startup_dir=startup, desktop_dir=desktop,
        )
        assert target.read_bytes() == merged
        assert target.stat().st_mtime_ns == merged_stat
        assert len(list(eq.glob(f"{target.name}.spinui-backup-*"))) == 1

        # Every public preset must merge its own audited geometry.
        for preset_key in LAYOUT_PRESETS:
            preset_target = eq / f"UI_{preset_key.replace('-', '')}_qeynos_LO1.ini"
            original = b"[Main]\nUISkin=old\n[MainChat]\nXRef=right\nYRef=bottom\nXPos=1%\nYPos=2%\nShow=0\n[ChatManager]\nChannelMap0=71\n"
            preset_target.write_bytes(original)
            preset_app = root / f"app-{preset_key}"
            preset_startup = root / f"startup-{preset_key}"
            preset_desktop = root / f"desktop-{preset_key}"
            install_payload(
                payload, eq, install_layout=True, layout_target=preset_target,
                layout_preset=preset_key, run_at_startup=False,
                desktop_shortcut=False, app_dir=preset_app,
                startup_dir=preset_startup, desktop_dir=preset_desktop,
            )
            preset_result = preset_target.read_text(encoding="utf-8")
            expected_offset = list(LAYOUT_PRESETS).index(preset_key) * 100 + mainchat_index
            assert f"XPos={expected_offset}.125000%" in preset_result
            assert "Show=0" not in preset_result and "Show=1" in preset_result
            assert "ChannelMap0=71" not in preset_result
            assert "ChannelMap0=99" in preset_result
            assert "ChatWindow0_Name=SOURCE" in preset_result
            preset_backups = list(eq.glob(f"{preset_target.name}.spinui-backup-*"))
            assert len(preset_backups) == 1 and preset_backups[0].read_bytes() == original

        # Resolution profiles are separate allowlisted sources; selecting
        # 2048x1080 must not silently fall back to the 3440x1440 geometry.
        wide_target = eq / "UI_Wide_qeynos_LO1.ini"
        wide_target.write_bytes(
            b"[Main]\nUISkin=old\n[MainChat]\nXPos=1%\n[ChatManager]\n")
        install_payload(
            payload, eq, install_layout=True, layout_target=wide_target,
            layout_preset="combat-focus", resolution_profile="2048x1080",
            run_at_startup=False, desktop_shortcut=False,
            app_dir=root / "app-wide", startup_dir=root / "startup-wide",
            desktop_dir=root / "desktop-wide",
        )
        wide_text = wide_target.read_text(encoding="utf-8")
        wide_offset = (
            (list(RESOLUTION_PROFILES).index("2048x1080") + 1) * 5
            + mainchat_index)
        assert f"XPos={wide_offset}.125000%" in wide_text

        collision_backup_target = eq / "UI_Backups_qeynos_LO1.ini"
        collision_backup_target.write_bytes(b"[Main]\nUISkin=old\n")
        first_original = collision_backup_target.read_bytes()
        for preset_key in ("combat-focus", "social-focus"):
            update = prepare_layout_update(
                payload / "layouts" / preset_key / LAYOUT_NAME,
                collision_backup_target, allow_create=False,
            )
            commit_layout_update(update)
        collision_backups = sorted(eq.glob(f"{collision_backup_target.name}.spinui-backup-*"))
        assert len(collision_backups) == 2
        assert len({path.name for path in collision_backups}) == 2
        assert any(path.read_bytes() == first_original for path in collision_backups)
        # A target without [ChatManager] gains the preset's complete section.
        collision_bytes = collision_backup_target.read_bytes()
        assert b"[ChatManager]\nChannelMap0=99\nChatWindow0_Name=SOURCE\n" in collision_bytes

        # Keep Existing performs no target write, backup, or timestamp change.
        untouched = eq / "UI_Untouched_qeynos_LO1.ini"
        untouched.write_text("leave me alone", encoding="utf-8")
        untouched_stat = untouched.stat().st_mtime_ns
        keep_result = install_payload(
            payload, eq, install_layout=False, layout_target=untouched,
            layout_preset="../ignored-while-disabled", run_at_startup=False,
            desktop_shortcut=False, app_dir=root / "app-keep",
            startup_dir=root / "startup-keep", desktop_dir=root / "desktop-keep",
        )
        assert untouched.read_text(encoding="utf-8") == "leave me alone"
        assert untouched.stat().st_mtime_ns == untouched_stat
        assert not list(eq.glob(f"{untouched.name}.spinui-backup-*"))
        assert "Kept the existing character layout unchanged" in keep_result

        # Compatibility: callers omitting layout_preset use the top-level file,
        # but still receive the same surgical merge.
        legacy_target = eq / "UI_Legacy_qeynos_LO1.ini"
        legacy_target.write_text("[Main]\nUISkin=legacy\n[ChatManager]\nChannelMap0=8\n", encoding="utf-8")
        install_payload(
            payload, eq, install_layout=True, layout_target=legacy_target,
            run_at_startup=False, desktop_shortcut=False,
            app_dir=root / "app-legacy", startup_dir=root / "startup-legacy",
            desktop_dir=root / "desktop-legacy",
        )
        legacy_text = legacy_target.read_text(encoding="utf-8")
        assert "UISkin=spinui_reloaded" in legacy_text
        assert "ChannelMap0=8" not in legacy_text
        assert "ChannelMap0=99" in legacy_text and "ChatWindow0_Name=SOURCE" in legacy_text

        # Manual target names preserve character casing and canonicalize all servers.
        assert SERVER_TOKEN_BY_DISPLAY == {
            "Erudin (European)": "erudin", "Freeport": "freeport",
            "Halas": "halas", "Neriak": "neriak", "Oggok": "oggok",
            "Paineel (European)": "paineel", "Qeynos": "qeynos",
            "Rivervale": "rivervale",
        }
        for server in LEGENDS_SERVERS:
            assert manual_layout_filename("Spin", server.token) == (
                f"UI_Spin_{server.token}_LO1.ini"
            )
        assert manual_layout_filename("mIxEdCase", "qeynos") == "UI_mIxEdCase_qeynos_LO1.ini"
        for invalid in ("", "Spin ", " Spin", "Spin_", "../Spin", "Spin/Alt",
                        "Spin\\Alt", "Spin:Alt", "Spin.", "NUL", "Spïn", "A" * 33):
            expect_error(ValueError, lambda invalid=invalid: validate_character_name(invalid))
        expect_error(ValueError, lambda: manual_layout_filename("Spin", "unknown"))

        # A new manual target is seeded once; a case-insensitive collision is merged.
        new_target = eq / manual_layout_filename("Fresh", "freeport")
        install_payload(
            payload, eq, install_layout=True, layout_target=new_target,
            layout_preset="social-focus", create_layout_target=True,
            run_at_startup=False, desktop_shortcut=False,
            app_dir=root / "app-new", startup_dir=root / "startup-new",
            desktop_dir=root / "desktop-new",
        )
        new_bytes = new_target.read_bytes()
        assert b"UISkin=spinui_reloaded" in new_bytes
        expected_new_x = 100 + mainchat_index
        assert b"[MainChat]" in new_bytes
        assert f"XPos={expected_new_x}.125000%".encode() in new_bytes
        # New files include layout visibility and the wholesale ChatManager,
        # but never source-only keys outside the audited boundary.
        assert b"Show=1\n" in new_bytes and b"Alpha=111\n" in new_bytes
        assert b"FadeToAlpha=190\n" in new_bytes and b"Fades=1\n" in new_bytes
        assert b"[ChatManager]\nChannelMap0=99\nChatWindow0_Name=SOURCE\n" in new_bytes
        for forbidden in (b"SourceOnly", b"Locked="):
            assert forbidden not in new_bytes, forbidden
        assert b"[HotButtonWnd]\nINIVersion=2\n" in new_bytes
        assert not list(eq.glob(f"{new_target.name}.spinui-backup-*"))
        collision = validate_layout_target(
            eq, eq / "UI_fresh_freeport_LO1.ini", allow_create=True
        )
        assert collision.name == new_target.name
        new_target.write_bytes(b"[Main]\nUISkin=custom\n[ChatManager]\nChannelMap0=55\n")
        install_payload(
            payload, eq, install_layout=True,
            layout_target=eq / "UI_fresh_freeport_LO1.ini",
            layout_preset="hybrid", create_layout_target=True,
            run_at_startup=False, desktop_shortcut=False,
            app_dir=root / "app-collision", startup_dir=root / "startup-collision",
            desktop_dir=root / "desktop-collision",
        )
        collision_merged = new_target.read_bytes()
        assert b"ChannelMap0=55" not in collision_merged
        assert b"ChannelMap0=99" in collision_merged

        expect_error(ValueError, lambda: resolve_layout_source(payload, "../combat-focus"))
        expect_error(ValueError, lambda: resolve_layout_source(payload, "original"))
        expect_error(ValueError, lambda: validate_layout_target(eq, None))
        expect_error(
            ValueError,
            lambda: validate_layout_target(eq, root / "UI_Outside_qeynos_LO1.ini"),
        )
        missing = eq / "UI_Missing_qeynos_LO1.ini"
        expect_error(ValueError, lambda: validate_layout_target(eq, missing))
        assert character_layout_label(target) == "Test  ·  qeynos  ·  Layout 1"
        assert character_layout_label(Path("not-a-layout.ini")) == "not-a-layout.ini"
        assert layout_review(KEEP_LAYOUT, None)[0] == "KEEP EXISTING"
        assert layout_review("hybrid", target)[0] == "HYBRID · 3440×1440"
        expect_error(ValueError, lambda: layout_review("original", target))
        expect_error(
            ValueError,
            lambda: layout_review("hybrid", target, "9999x9999"))
        expect_error(
            ValueError,
            lambda: resolve_layout_source(
                payload, "combat-focus", "9999x9999"))

        # Duplicate audited data fails closed before any target/backup write.
        duplicate_source = root / "duplicate-source.ini"
        duplicate_source.write_bytes(
            preset_bytes("combat-focus") + b"[MainChat]\nXPos=1%\n"
        )
        duplicate_target = eq / "UI_Duplicate_qeynos_LO1.ini"
        duplicate_target.write_bytes(b"[Main]\nUISkin=old\n")
        before_duplicate = duplicate_target.read_bytes()
        expect_error(
            ValueError,
            lambda: prepare_layout_update(duplicate_source, duplicate_target, allow_create=False),
        )
        assert duplicate_target.read_bytes() == before_duplicate
        assert not list(eq.glob(f"{duplicate_target.name}.spinui-backup-*"))
        duplicate_key_target = eq / "UI_DuplicateKey_qeynos_LO1.ini"
        duplicate_key_original = (
            b"[Main]\nUISkin=old\n[MainChat]\nXRef=left\nYRef=top\n"
            b"XPos=1%\nXPos=2%\nYPos=3%\n"
        )
        duplicate_key_target.write_bytes(duplicate_key_original)
        expect_error(
            ValueError,
            lambda: prepare_layout_update(
                payload / "layouts" / "combat-focus" / LAYOUT_NAME,
                duplicate_key_target, allow_create=False,
            ),
        )
        assert duplicate_key_target.read_bytes() == duplicate_key_original
        invalid_source = root / "invalid-source.ini"
        invalid_source.write_bytes(
            preset_bytes("combat-focus").replace(b"XPos=0.125000%", b"XPos=oops")
        )
        expect_error(
            ValueError,
            lambda: prepare_layout_update(invalid_source, duplicate_target, allow_create=False),
        )

        # Invalid visibility values and a malformed or missing ChatManager
        # fail closed before any target write.
        for breakage in (
            (b"Show=1", b"Show=2"),
            (b"Alpha=111", b"Alpha=300"),
            (b"ChannelMap0=99", b"Channel Map0=99"),
            (b"[ChatManager]", b"[ChatManagerRenamed]"),
        ):
            broken_source = root / "broken-source.ini"
            broken_source.write_bytes(preset_bytes("combat-focus").replace(*breakage))
            expect_error(
                ValueError,
                lambda source=broken_source: prepare_layout_update(
                    source, duplicate_target, allow_create=False
                ),
            )
        assert duplicate_target.read_bytes() == before_duplicate

        # Windows-1252 comments and LF style remain intact.
        cp_target = eq / "UI_CpTest_qeynos_LO1.ini"
        cp_original = b"; caf\xe9\n[Main]\nUISkin=old\n[MainChat]\nXRef=left\nYRef=top\nXPos=1%\nYPos=2%\nNote=ol\xe9\n"
        cp_target.write_bytes(cp_original)
        cp_update = prepare_layout_update(
            payload / "layouts" / "combat-focus" / LAYOUT_NAME,
            cp_target, allow_create=False,
        )
        commit_layout_update(cp_update)
        assert b"; caf\xe9\n" in cp_target.read_bytes() and b"Note=ol\xe9\n" in cp_target.read_bytes()
        assert b"\r\n" not in cp_target.read_bytes()

        # A replace failure leaves the original exact and cleans temp/backup files.
        failure_target = eq / "UI_Failure_qeynos_LO1.ini"
        failure_target.write_bytes(b"[Main]\nUISkin=old\n")
        failure_update = prepare_layout_update(
            payload / "layouts" / "combat-focus" / LAYOUT_NAME,
            failure_target, allow_create=False,
        )
        original_replace = os.replace
        def fail_target_replace(source, destination):
            if Path(destination) == failure_target:
                raise PermissionError("injected replace failure")
            return original_replace(source, destination)
        os.replace = fail_target_replace
        try:
            expect_error(PermissionError, lambda: commit_layout_update(failure_update))
        finally:
            os.replace = original_replace
        assert failure_target.read_bytes() == b"[Main]\nUISkin=old\n"
        assert not list(eq.glob(f"{failure_target.name}.spinui-backup-*"))
        assert not list(eq.glob(f".{failure_target.name}.spinui-*.tmp"))

        # Backup-name races never delete a file this installer did not create.
        backup_race_target = eq / "UI_BackupRace_qeynos_LO1.ini"
        backup_race_target.write_bytes(b"[Main]\nUISkin=old\n")
        backup_race_update = prepare_layout_update(
            payload / "layouts" / "combat-focus" / LAYOUT_NAME,
            backup_race_target, allow_create=False,
        )
        foreign_backup = eq / "foreign-existing-backup"
        foreign_backup.write_bytes(b"do not delete")
        original_unique_backup = globals()["_unique_backup_path"]
        globals()["_unique_backup_path"] = lambda _target: foreign_backup
        try:
            expect_error(FileExistsError, lambda: commit_layout_update(backup_race_update))
        finally:
            globals()["_unique_backup_path"] = original_unique_backup
        assert foreign_backup.read_bytes() == b"do not delete"
        assert backup_race_target.read_bytes() == b"[Main]\nUISkin=old\n"

        # A new manual target that appears after preparation is never replaced.
        new_race_target = eq / "UI_Appeared_qeynos_LO1.ini"
        new_race_update = prepare_layout_update(
            payload / "layouts" / "combat-focus" / LAYOUT_NAME,
            new_race_target, allow_create=True,
        )
        original_publish_new = globals()["_publish_new_target"]
        def inject_new_target_race(staged, destination):
            Path(destination).write_bytes(b"appeared")
            return original_publish_new(staged, destination)
        globals()["_publish_new_target"] = inject_new_target_race
        try:
            expect_error(OSError, lambda: commit_layout_update(new_race_update))
        finally:
            globals()["_publish_new_target"] = original_publish_new
        assert new_race_target.read_bytes() == b"appeared"
        assert not list(eq.glob(f".{new_race_target.name}.spinui-*.tmp"))

        # A running EQ client blocks the operation before any target or backup write.
        blocked_target = eq / "UI_Blocked_qeynos_LO1.ini"
        blocked_original = b"[Main]\nUISkin=old\n[ChatManager]\nChannelMap0=2\n"
        blocked_target.write_bytes(blocked_original)
        original_process_check = globals()["process_is_running"]
        globals()["process_is_running"] = lambda image: image.casefold() == "eqgame.exe"
        try:
            expect_error(
                RuntimeError,
                lambda: install_payload(
                    payload, eq, install_layout=True, layout_target=blocked_target,
                    layout_preset="combat-focus", require_eq_closed=True,
                    run_at_startup=False, desktop_shortcut=False,
                    app_dir=root / "app-blocked", startup_dir=root / "startup-blocked",
                    desktop_dir=root / "desktop-blocked",
                ),
            )
        finally:
            globals()["process_is_running"] = original_process_check
        assert blocked_target.read_bytes() == blocked_original
        assert not list(eq.glob(f"{blocked_target.name}.spinui-backup-*"))

        (app / "loremaster_config.json").write_text("null", encoding="utf-8")
        configure_loremaster(eq.resolve(), app)
        repaired = json.loads((app / "loremaster_config.json").read_text())
        assert repaired == {"log_dir": str(eq.resolve())}
        if os.name == "nt":
            set_desktop_shortcut(app / LOREMASTER_NAME, True, desktop)
            assert (desktop / DESKTOP_LINK).is_file()
            set_desktop_shortcut(app / LOREMASTER_NAME, False, desktop)
            assert not (desktop / DESKTOP_LINK).exists()
        else:
            # A native Linux executable, never a Windows exe -- Loremaster is
            # never wrapped with wine on this platform.
            linux_executable = app / LOREMASTER_LINUX_DESTINATION_NAME
            linux_executable.write_bytes(b"fake appimage")
            set_desktop_shortcut(linux_executable, True, desktop)
            entry = desktop / DESKTOP_LINK
            assert entry.is_file()
            entry_text = entry.read_text(encoding="utf-8")
            assert "[Desktop Entry]" in entry_text
            assert f"Exec={shlex.quote(str(linux_executable))}\n" in entry_text
            assert "wine" not in entry_text
            assert os.access(entry, os.X_OK)
            set_desktop_shortcut(linux_executable, False, desktop)
            assert not entry.exists()
            set_startup_shortcut(linux_executable, True, startup)
            startup_entry = startup / STARTUP_LINK
            assert startup_entry.is_file()
            startup_text = startup_entry.read_text(encoding="utf-8")
            assert "--wait-for-eq" in startup_text
            assert "wine" not in startup_text
            set_startup_shortcut(linux_executable, False, startup)
            assert not startup_entry.exists()

    # Skins: the payload can ship more than one; install_payload copies
    # whichever is selected, and a layout preset authored only for
    # SKIN_NAME fails closed (no target write) against a different skin.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        payload = root / "payload"
        eq = root / "EverQuest Legends"
        (payload / SKIN_NAME).mkdir(parents=True)
        (payload / SKIN_NAME / "EQUI.xml").write_text("<xml/>", encoding="utf-8")
        (payload / "spinui_glass").mkdir(parents=True)
        (payload / "spinui_glass" / "EQUI.xml").write_text("<glass/>", encoding="utf-8")
        # Deliberately only the Windows exe, no Loremaster-*.AppImage: on
        # Linux this is the common "ran from a source checkout" case, and
        # must not stop the skin from installing (see requirement below).
        (payload / LOREMASTER_NAME).write_bytes(b"loremaster")
        eq.mkdir()
        (eq / "eqgame.exe").write_bytes(b"")
        glass_result = install_payload(
            payload, eq, install_layout=False, layout_target=None,
            run_at_startup=False, desktop_shortcut=False,
            app_dir=root / "app-glass", startup_dir=root / "startup-glass",
            desktop_dir=root / "desktop-glass", skin_name="spinui_glass",
        )
        assert (eq / "uifiles" / "spinui_glass" / "EQUI.xml").read_text(encoding="utf-8") == "<glass/>"
        assert not (eq / "uifiles" / SKIN_NAME).exists()
        if os.name != "nt":
            # No native artifact: the skin still installs cleanly (asserted
            # above), and Loremaster is honestly skipped, not silently
            # wrapped in wine or copied as the Windows exe.
            assert any("Skipped Loremaster" in line and "AppImage" in line
                      for line in glass_result)
            assert not (root / "app-glass").exists()
            assert not any("wine" in line.casefold() for line in glass_result)
        expect_error(ValueError, lambda: install_payload(
            payload, eq, install_layout=False, layout_target=None,
            run_at_startup=False, desktop_shortcut=False,
            app_dir=root / "app-badskin", startup_dir=root / "startup-badskin",
            desktop_dir=root / "desktop-badskin", skin_name="not-a-real-skin",
        ))

        profile_dir = payload / "layouts" / "profiles" / DEFAULT_RESOLUTION_PROFILE / "combat-focus"
        profile_dir.mkdir(parents=True)
        (profile_dir / LAYOUT_NAME).write_bytes(preset_bytes("combat-focus"))
        glass_target = eq / "UI_Glass_qeynos_LO1.ini"
        glass_original = b"[Main]\nUISkin=old\n[ChatManager]\nChannelMap0=1\n"
        glass_target.write_bytes(glass_original)
        expect_error(ValueError, lambda: install_payload(
            payload, eq, install_layout=True, layout_target=glass_target,
            layout_preset="combat-focus", run_at_startup=False, desktop_shortcut=False,
            app_dir=root / "app-glass-layout", startup_dir=root / "startup-glass-layout",
            desktop_dir=root / "desktop-glass-layout", skin_name="spinui_glass",
        ))
        assert glass_target.read_bytes() == glass_original
        assert not list(eq.glob(f"{glass_target.name}.spinui-backup-*"))

    # local_app_data()/startup_folder() follow XDG on Linux instead of
    # writing %APPDATA%-shaped paths; Windows keeps its existing env contract.
    with tempfile.TemporaryDirectory() as td:
        original_environ = dict(os.environ)
        try:
            if os.name == "nt":
                os.environ["LOCALAPPDATA"] = str(Path(td) / "local")
                os.environ["APPDATA"] = str(Path(td) / "roaming")
                assert local_app_data() == Path(td) / "local" / "SpinsLoremaster"
                assert startup_folder() == (
                    Path(td) / "roaming" / "Microsoft" / "Windows"
                    / "Start Menu" / "Programs" / "Startup")
            else:
                os.environ["HOME"] = td
                os.environ.pop("XDG_DATA_HOME", None)
                os.environ.pop("XDG_CONFIG_HOME", None)
                assert local_app_data() == Path(td) / ".local" / "share" / "SpinsLoremaster"
                assert startup_folder() == Path(td) / ".config" / "autostart"
                os.environ["XDG_DATA_HOME"] = str(Path(td) / "xdg-data")
                os.environ["XDG_CONFIG_HOME"] = str(Path(td) / "xdg-config")
                assert local_app_data() == Path(td) / "xdg-data" / "SpinsLoremaster"
                assert startup_folder() == Path(td) / "xdg-config" / "autostart"
        finally:
            os.environ.clear()
            os.environ.update(original_environ)

    # Wine/Proton prefix discovery: bounded, tolerant of missing/garbage
    # entries, and additive to (never a replacement for) native discovery.
    with tempfile.TemporaryDirectory() as td:
        original_environ = dict(os.environ)
        try:
            # Path.home() reads USERPROFILE on Windows and has ignored HOME
            # there since Python 3.8, so setting HOME alone left discovery
            # pointed at the runner's real profile.  find_eq_roots() consults
            # the Wine prefixes on every platform, so this has to hold on all
            # of them.
            os.environ["HOME"] = td
            os.environ["USERPROFILE"] = td
            os.environ.pop("WINEPREFIX", None)
            home = Path(td)
            assert wine_prefixes() == []
            assert find_wine_eq_roots() == []

            eq_dir = home / ".wine" / "drive_c" / "Program Files (x86)" / "Sony" / "EverQuest"
            eq_dir.mkdir(parents=True)
            (eq_dir / "eqgame.exe").write_bytes(b"")
            assert home / ".wine" in wine_prefixes()
            assert eq_dir in find_wine_eq_roots()
            assert eq_dir in find_eq_roots()

            explicit_prefix = home / "custom-prefix"
            (explicit_prefix / "drive_c").mkdir(parents=True)
            os.environ["WINEPREFIX"] = str(explicit_prefix)
            assert explicit_prefix in wine_prefixes()

            steam_lib_eq = (
                home / ".steam" / "steam" / "steamapps" / "compatdata" / "480" / "pfx"
                / "drive_c" / "Program Files (x86)" / "Steam" / "steamapps" / "common"
                / "EverQuest Legends")
            steam_lib_eq.mkdir(parents=True)
            (steam_lib_eq / "eqgame.exe").write_bytes(b"")
            assert (home / ".steam" / "steam" / "steamapps" / "compatdata"
                    / "480" / "pfx") in wine_prefixes()
            assert steam_lib_eq in find_wine_eq_roots()

            # A file where a directory is expected must not raise.
            games_root = home / "Games"
            games_root.mkdir()
            (games_root / "not-a-prefix").write_bytes(b"file, not a wine prefix directory")
            wine_prefixes()
        finally:
            os.environ.clear()
            os.environ.update(original_environ)

    # The running-client guard reads /proc directly on Linux so it still
    # blocks an install over a live Wine-hosted eqgame.exe.
    with tempfile.TemporaryDirectory() as td:
        fake_proc = Path(td)
        assert _linux_process_running("eqgame.exe", proc_root=fake_proc) is False
        pid_dir = fake_proc / "4242"
        pid_dir.mkdir()
        (pid_dir / "comm").write_text("eqgame.exe\n", encoding="utf-8")
        (pid_dir / "cmdline").write_bytes(b"Z:\\EQLegends\\eqgame.exe\x00")
        assert _linux_process_running("eqgame.exe", proc_root=fake_proc) is True
        assert _linux_process_running("Loremaster.exe", proc_root=fake_proc) is False
        # comm truncates/varies under Wine; cmdline is the fallback match.
        (pid_dir / "comm").write_text("wine-preloader\n", encoding="utf-8")
        assert _linux_process_running("eqgame.exe", proc_root=fake_proc) is True
        (fake_proc / "self").mkdir()  # non-numeric entries are skipped, not fatal
        assert _linux_process_running("eqgame.exe", proc_root=fake_proc) is True

    # Linux Loremaster artifact matching: prefer AppImage, matched by glob
    # since electron-builder's filename embeds the release version and arch.
    with tempfile.TemporaryDirectory() as td:
        artifact_payload = Path(td)
        assert find_linux_loremaster_artifact(artifact_payload) is None
        (artifact_payload / "Loremaster-1.2.3-x64.AppImage").write_bytes(b"a")
        assert find_linux_loremaster_artifact(artifact_payload) == (
            artifact_payload / "Loremaster-1.2.3-x64.AppImage")
        (artifact_payload / "Loremaster-1.2.3-x64.tar.gz").write_bytes(b"b")
        # AppImage still wins even with a same-version tar.gz alongside it.
        assert find_linux_loremaster_artifact(artifact_payload) == (
            artifact_payload / "Loremaster-1.2.3-x64.AppImage")
        (artifact_payload / "Loremaster-1.2.3-x64.AppImage").unlink()
        # tar.gz support is intentionally not implemented yet: absent an
        # AppImage this is the same "nothing usable" case as if the payload
        # had no artifact at all, and install_payload() must skip cleanly.
        assert find_linux_loremaster_artifact(artifact_payload) is None
        (artifact_payload / SKIN_NAME).mkdir()
        (artifact_payload / SKIN_NAME / "EQUI.xml").write_text("<xml/>", encoding="utf-8")
        # Installing from a payload that holds no usable Loremaster is a Linux
        # shape: the skin lands and Loremaster is skipped with an explanation.
        # On Windows a payload without Loremaster.exe is a hard error by
        # design, so install_payload() itself raises and there is nothing here
        # to assert -- which is why the whole block, not just its assertions,
        # belongs behind the platform check.
        if os.name != "nt":
            with tempfile.TemporaryDirectory() as eq_td:
                artifact_eq = Path(eq_td)
                (artifact_eq / "eqgame.exe").write_bytes(b"")
                skip_result = install_payload(
                    artifact_payload, artifact_eq, install_layout=False, layout_target=None,
                    run_at_startup=False, desktop_shortcut=False,
                    app_dir=artifact_payload / "app", startup_dir=artifact_payload / "startup",
                    desktop_dir=artifact_payload / "desktop",
                )
                assert (artifact_eq / "uifiles" / SKIN_NAME / "EQUI.xml").is_file()
                assert any("Skipped Loremaster" in line for line in skip_result)
                # This payload still holds the tar.gz, so the skip names that
                # archive and the binary to run instead of implying nothing was
                # downloaded. The releases-page wording belongs to the
                # nothing-usable-at-all case asserted below.
                detail = [line for line in skip_result if "Skipped Loremaster" in line]
                assert any("Loremaster-1.2.3-x64.tar.gz" in line for line in detail)
                assert any("./loremaster" in line for line in detail)
                assert not any("releases page" in line for line in detail)

        if os.name != "nt":
            assert "tar.gz" in _linux_loremaster_skip_detail(artifact_payload)
            (artifact_payload / "Loremaster-1.2.3-x64.tar.gz").unlink()
            empty_detail = _linux_loremaster_skip_detail(artifact_payload)
            assert "releases page" in empty_detail
            assert "tar.gz" not in empty_detail

    # stop_running_loremaster() on Linux signals real processes directly
    # (there is no tasklist/taskkill equivalent), verified against an actual
    # spawned process named like the installed build's executableName.
    if os.name != "nt":
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / LOREMASTER_LINUX_PROCESS_NAME
            script.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
            script.chmod(0o755)
            proc = subprocess.Popen([str(script)])
            # A terminated child stays a visible /proc zombie (comm and all)
            # until this, its direct parent, reaps it -- unlike a real
            # Loremaster process, which isn't parented by the installer. A
            # background wait() reaps it the instant it exits so the test
            # sees the same "gone from /proc" outcome a real launch would.
            reaper = threading.Thread(target=proc.wait, daemon=True)
            reaper.start()
            try:
                for _ in range(50):
                    if process_is_running(LOREMASTER_LINUX_PROCESS_NAME):
                        break
                    time.sleep(0.05)
                assert process_is_running(LOREMASTER_LINUX_PROCESS_NAME)
                assert stop_running_loremaster(LOREMASTER_LINUX_PROCESS_NAME) is True
                assert not process_is_running(LOREMASTER_LINUX_PROCESS_NAME)
            finally:
                if proc.poll() is None:
                    proc.kill()
                reaper.join(timeout=5)
        assert stop_running_loremaster(LOREMASTER_LINUX_PROCESS_NAME) is False

    print("SpinUI installer selftest: ALL PASS")
    return 0


def _cli_layout_target(eq_root: Path, args: argparse.Namespace) -> tuple[Path | None, bool]:
    """Resolve --layout-target or --character/--server into a target path.

    Mirrors the GUI's two target modes (an existing detected character, or a
    manual/new one) using the same validated helpers the GUI uses, so path
    traversal and name checks are never duplicated here.
    """
    if args.layout_target:
        return eq_root / args.layout_target, args.create_layout
    if args.character or args.server:
        if not (args.character and args.server):
            raise ValueError("--character and --server must be used together.")
        filename = manual_layout_filename(args.character, args.server)
        return eq_root / filename, args.create_layout
    existing = character_layouts(eq_root)
    if len(existing) == 1:
        return existing[0], args.create_layout
    if not existing:
        raise ValueError(
            "No character layout INI was found in --eq-dir. Log into the character "
            "once and close EverQuest, or pass --character/--server with --create-layout."
        )
    names = ", ".join(path.name for path in existing)
    raise ValueError(
        f"Multiple character layouts were found ({names}); choose one with --layout-target."
    )


def _dry_run_plan(payload: Path, eq_root: Path, *, install_layout: bool,
                  layout_target: Path | None, layout_preset: str | None,
                  resolution_profile: str, create_layout_target: bool,
                  skin_name: str) -> list[str]:
    """Validate an install exactly as install_payload() would, without writing.

    Reuses the same pure validation/preparation helpers install_payload()
    calls (is_eq_root, resolve_layout_source, validate_layout_target,
    prepare_layout_update) so the reported plan can never silently diverge
    from what a real install would do. prepare_layout_update only reads
    bytes and builds an in-memory LayoutUpdate; committing it is a separate,
    intentionally skipped step (commit_layout_update).
    """
    payload = payload.resolve()
    eq_root = eq_root.resolve()
    if not is_eq_root(eq_root):
        raise ValueError("Choose the EverQuest folder that contains eqgame.exe.")
    if skin_name not in AVAILABLE_SKINS:
        raise ValueError(f"Unknown skin: {skin_name!r}.")
    skin_source = payload / skin_name
    lore_source: Path | None = (
        payload / LOREMASTER_NAME if os.name == "nt"
        else find_linux_loremaster_artifact(payload)
    )
    if not skin_source.is_dir():
        raise FileNotFoundError(f"Release payload is missing {skin_name}.")
    if os.name == "nt" and not lore_source.is_file():
        raise FileNotFoundError(f"Release payload is missing {LOREMASTER_NAME}.")

    lines = [f"Install {skin_name} to {eq_root / 'uifiles' / skin_name}"]
    if lore_source is not None:
        destination_name = LOREMASTER_NAME if os.name == "nt" else LOREMASTER_LINUX_DESTINATION_NAME
        lines.append(f"Install Loremaster to {local_app_data() / destination_name}")
    else:
        lines.append(
            "Skip Loremaster: " + _linux_loremaster_skip_detail(payload)
        )
    if install_layout:
        if resolution_profile not in RESOLUTION_PROFILES:
            raise ValueError(f"Unknown resolution profile: {resolution_profile!r}.")
        layout_source = resolve_layout_source(payload, layout_preset, resolution_profile)
        target = validate_layout_target(eq_root, layout_target, allow_create=create_layout_target)
        update = prepare_layout_update(
            layout_source, target, allow_create=create_layout_target, expected_skin=skin_name)
        if not update.changed:
            lines.append(f"{target.name} already matches this layout; no change")
        elif update.created:
            lines.append(f"Would create {target.name} with the {layout_preset} layout")
        else:
            lines.append(f"Would apply the {layout_preset} layout to {target.name} (backup created)")
    else:
        lines.append("Keep the existing character layout unchanged")
    return lines


def _print_presets() -> int:
    print("Layout presets:")
    for preset in LAYOUT_PRESETS.values():
        print(f"  {preset.key:<14} {preset.title} - {preset.tagline}")
    print()
    print("Resolution profiles:")
    for profile in RESOLUTION_PROFILES.values():
        marker = " (default)" if profile.key == DEFAULT_RESOLUTION_PROFILE else ""
        print(f"  {profile.key:<10} {profile.label}{marker}")
    print()
    print("Skins:")
    for skin in AVAILABLE_SKINS:
        marker = " (default)" if skin == SKIN_NAME else ""
        print(f"  {skin}{marker}")
    return 0


def _cli_install(args: argparse.Namespace) -> int:
    payload = release_root()
    if args.eq_dir is not None:
        eq_root = Path(args.eq_dir).expanduser()
    else:
        roots = find_eq_roots()
        if not roots:
            print("No EverQuest folder was auto-detected. Pass --eq-dir PATH.", file=sys.stderr)
            return 2
        eq_root = roots[0]
    if not is_eq_root(eq_root):
        print(f"{eq_root} does not contain eqgame.exe.", file=sys.stderr)
        return 2

    install_layout = args.layout is not None
    target: Path | None = None
    create_layout_target = False
    try:
        if install_layout:
            target, create_layout_target = _cli_layout_target(eq_root, args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.dry_run:
        try:
            lines = _dry_run_plan(
                payload, eq_root, install_layout=install_layout, layout_target=target,
                layout_preset=args.layout, resolution_profile=args.resolution,
                create_layout_target=create_layout_target, skin_name=args.skin,
            )
        except (ValueError, FileNotFoundError, OSError) as exc:
            print(f"DRY RUN: would fail - {exc}", file=sys.stderr)
            return 2
        print(f"DRY RUN against {eq_root}: no files were written.")
        for line in lines:
            print(f"  - {line}")
        return 0

    try:
        results = install_payload(
            payload, eq_root, install_layout=install_layout, layout_target=target,
            run_at_startup=args.startup_shortcut, desktop_shortcut=args.desktop_shortcut,
            replace_running=args.replace_running,
            require_eq_closed=not args.allow_running,
            layout_preset=args.layout, resolution_profile=args.resolution,
            create_layout_target=create_layout_target, skin_name=args.skin,
        )
    except (ValueError, FileNotFoundError, RuntimeError, OSError) as exc:
        print(f"Install failed: {exc}", file=sys.stderr)
        return 1
    print(f"Installed to {eq_root}:")
    for line in results:
        print(f"  - {line}")
    return 0


def run_gui() -> int:
    if os.name != "nt":
        raise RuntimeError("SpinUI Installer is intended for Windows.")
    enable_windows_dpi_awareness()
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    payload = release_root()
    root = tk.Tk()
    root.title(APP_NAME)
    root.configure(bg=BG)
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    window_w = min(900, max(740, screen_w - 64))
    window_h = min(700, max(590, screen_h - 72))
    root.geometry(
        f"{window_w}x{window_h}+{max(0, (screen_w - window_w) // 2)}"
        f"+{max(0, (screen_h - window_h) // 2)}"
    )
    root.minsize(min(780, window_w), min(620, window_h))

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TCombobox", fieldbackground=RAISED, background=RAISED,
                    foreground=TEXT, arrowcolor=CYAN, bordercolor=LINE)
    style.map("TCombobox", fieldbackground=[("readonly", RAISED)],
              foreground=[("readonly", TEXT)])
    style.configure("Spin.Horizontal.TProgressbar", troughcolor=PANEL,
                    background=CYAN, bordercolor=LINE, lightcolor=CYAN,
                    darkcolor=CYAN)

    def flat_button(parent, text: str, command, *, primary: bool = False):
        bg = CYAN if primary else RAISED
        fg = BG if primary else TEXT
        return tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=(GOLD_BRIGHT if primary else LINE),
            activeforeground=BG if primary else TEXT, relief="flat", bd=0,
            highlightthickness=1, highlightbackground=(CYAN if primary else LINE),
            highlightcolor=GOLD_BRIGHT, font=("Segoe UI Semibold", 10),
            padx=18, pady=8, cursor="hand2", takefocus=True,
        )

    tk.Frame(root, bg=GOLD, height=2).pack(fill="x")
    header = tk.Frame(root, bg=PANEL, padx=30, pady=14)
    header.pack(fill="x")
    tk.Label(header, text="SPIN'S UI RELOADED", bg=PANEL, fg=GOLD_BRIGHT,
             font=("Georgia", 18, "bold")).pack(side="left")
    tk.Label(header, text="OBSIDIAN · VENOM · EMBER   /   WINDOWS INSTALLER",
             bg=PANEL, fg=CYAN, font=("Segoe UI Semibold", 9)).pack(
                 side="right", pady=(5, 0))
    tk.Frame(root, bg=EMBER, height=2).pack(fill="x")

    step_bar = tk.Frame(root, bg="#100b07", padx=30, pady=9)
    step_bar.pack(fill="x")
    step_labels: list[tk.Label] = []
    for index, title in enumerate(("1  INSTALL", "2  LAYOUT", "3  REVIEW")):
        label = tk.Label(
            step_bar, text=title, bg="#100b07", fg=DIM,
            font=("Segoe UI Semibold", 9), anchor="center",
        )
        label.pack(side="left", expand=True, fill="x")
        step_labels.append(label)

    body = tk.Frame(root, bg=BG, padx=30, pady=18)
    body.pack(fill="both", expand=True)
    pages = [tk.Frame(body, bg=BG) for _ in range(3)]

    # --- Step 1: locate EverQuest -----------------------------------------
    install_page = pages[0]
    tk.Label(install_page, text="EVERQUEST INSTALLATION", bg=BG, fg=GOLD,
             font=("Georgia", 9, "bold")).pack(anchor="w")
    tk.Label(install_page, text="Find the game. SpinUI handles the rest.", bg=BG, fg=TEXT,
             font=("Segoe UI Semibold", 18)).pack(anchor="w", pady=(5, 3))
    tk.Label(
        install_page,
        text=("The skin and Loremaster are always refreshed safely. Your character layout "
              "stays untouched unless you explicitly choose a preset on the next step."),
        bg=BG, fg=DIM, font=("Segoe UI", 10), justify="left", wraplength=790,
    ).pack(anchor="w", pady=(0, 16))

    location_card = tk.Frame(
        install_page, bg=PANEL, padx=16, pady=14,
        highlightthickness=1, highlightbackground=LINE,
    )
    location_card.pack(fill="x")
    tk.Label(location_card, text="FOLDER CONTAINING EQGAME.EXE", bg=PANEL, fg=GOLD,
             font=("Segoe UI Semibold", 8)).pack(anchor="w")
    path_row = tk.Frame(location_card, bg=PANEL)
    path_row.pack(fill="x", pady=(7, 5))
    path_var = tk.StringVar()
    path_entry = tk.Entry(path_row, textvariable=path_var, bg=RAISED, fg=TEXT,
                          insertbackground=CYAN, relief="flat", highlightthickness=1,
                          highlightbackground=LINE, highlightcolor=CYAN,
                          font=("Segoe UI", 10))
    path_entry.pack(side="left", fill="x", expand=True, ipady=7)
    browse = flat_button(path_row, "BROWSE", lambda: choose_folder())
    browse.pack(side="left", padx=(8, 0))
    detect = tk.Label(location_card, text="Searching for eqgame.exe…", bg=PANEL, fg=DIM,
                      font=("Segoe UI", 9))
    detect.pack(anchor="w")

    components = tk.Frame(install_page, bg=BG)
    components.pack(fill="x", pady=(18, 0))
    component_copy = (
        ("01", "SPINUI SKIN", "A clean exact-tree update; retired files cannot linger."),
        ("02", "LOREMASTER", "Real-time encounters, records, tray recovery, and Lore Lens."),
        ("03", "YOUR CONTROL", "No character layout changes unless you choose one."),
    )
    for column, (number, title, copy) in enumerate(component_copy):
        components.grid_columnconfigure(column, weight=1, uniform="component")
        card = tk.Frame(
            components, bg=PANEL, padx=14, pady=13,
            highlightthickness=1, highlightbackground=LINE,
        )
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))
        tk.Label(card, text=number, bg=PANEL, fg=CYAN,
                 font=("Georgia", 9, "bold")).pack(anchor="w")
        tk.Label(card, text=title, bg=PANEL, fg=TEXT,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w", pady=(5, 3))
        tk.Label(card, text=copy, bg=PANEL, fg=DIM, font=("Segoe UI", 9),
                 justify="left", wraplength=220).pack(anchor="w")

    # --- Step 2: choose the optional layout -------------------------------
    layout_page = pages[1]
    tk.Label(layout_page, text="CHARACTER LAYOUT", bg=BG, fg=GOLD,
             font=("Georgia", 9, "bold")).pack(anchor="w")
    tk.Label(layout_page, text="Choose what fits the way you play.", bg=BG, fg=TEXT,
             font=("Segoe UI Semibold", 18)).pack(anchor="w", pady=(5, 2))
    tk.Label(
        layout_page,
        text=("Keep Existing is recommended. If you apply a layout, choose the "
              "screen profile used by EverQuest and then the chat emphasis. "
              "Every profile preserves Spin's live HUD hierarchy without "
              "replacing unrelated character data."),
        bg=BG, fg=DIM, font=("Segoe UI", 10),
    ).pack(anchor="w", pady=(0, 4))
    resolution_hint = tk.Label(layout_page, text=resolution_note(None),
                               bg=BG, fg=CYAN, font=("Segoe UI", 9))
    resolution_hint.pack(anchor="w", pady=(0, 6))

    profile_row = tk.Frame(layout_page, bg=BG)
    profile_row.pack(fill="x", pady=(0, 12))
    tk.Label(
        profile_row, text="SCREEN PROFILE", bg=BG, fg=GOLD,
        font=("Segoe UI Semibold", 9),
    ).pack(side="left", padx=(0, 8))
    resolution_profile_var = tk.StringVar(
        value=PROFILE_KEY_TO_LABEL[DEFAULT_RESOLUTION_PROFILE])
    profile_combo = ttk.Combobox(
        profile_row,
        textvariable=resolution_profile_var,
        state="readonly",
        width=31,
        values=tuple(PROFILE_LABEL_TO_KEY),
    )
    profile_combo.pack(side="left")
    profile_selection_touched = {"value": False}

    layout_choice = tk.StringVar(value=KEEP_LAYOUT)
    keep_card = tk.Frame(
        layout_page, bg=PANEL, padx=12, pady=9,
        highlightthickness=1, highlightbackground=CYAN,
    )
    keep_card.pack(fill="x", pady=(0, 10))
    keep_radio = tk.Radiobutton(
        keep_card, variable=layout_choice, value=KEEP_LAYOUT,
        text="KEEP MY CURRENT LAYOUT  ·  RECOMMENDED",
        bg=PANEL, activebackground=PANEL, fg=TEXT, activeforeground=TEXT,
        selectcolor=RAISED, font=("Segoe UI Semibold", 10), anchor="w",
        takefocus=True, command=lambda: refresh_layout_selection(),
    )
    keep_radio.pack(fill="x")
    tk.Label(keep_card, text="Install the skin without moving a single existing window.",
             bg=PANEL, fg=DIM, font=("Segoe UI", 9)).pack(anchor="w", padx=22)

    preset_row = tk.Frame(layout_page, bg=BG)
    preset_row.pack(fill="both", expand=True)
    preset_cards: dict[str, tuple[tk.Frame, tk.Radiobutton]] = {}

    def draw_layout_schematic(canvas, preset: LayoutPreset) -> None:
        width, height = 238, 70
        canvas.create_rectangle(1, 1, width - 2, height - 2, outline=LINE)
        canvas.create_rectangle(82, 18, 115, 29, fill=RAISED, outline=CYAN)
        canvas.create_rectangle(122, 18, 155, 29, fill=RAISED, outline=GOLD)
        colors = ("#3c5a86", "#584428", "#6b3a1c")
        labels = ("MAIN", "SOCIAL", "COMBAT")
        total = sum(preset.chat_widths) + 16
        cursor = 7.0
        usable = width - 14
        for index, (chat_width, chat_height) in enumerate(
                zip(preset.chat_widths, preset.chat_heights)):
            block_width = max(28, usable * chat_width / total)
            block_height = 24 * chat_height / 280
            y0 = height - 7 - block_height
            canvas.create_rectangle(
                int(cursor), int(y0), int(cursor + block_width - 2), height - 7,
                fill=colors[index], outline=(CYAN if index == 2 else LINE),
            )
            if block_width >= 48:
                canvas.create_text(
                    int(cursor + (block_width - 2) / 2), int(y0 + block_height / 2),
                    text=labels[index], fill=TEXT, font=("Segoe UI", 6, "bold"),
                )
            cursor += block_width + (usable * 8 / total)

    def choose_layout(key: str) -> None:
        layout_choice.set(key)
        refresh_layout_selection()

    for column, preset in enumerate(LAYOUT_PRESETS.values()):
        preset_row.grid_columnconfigure(column, weight=1, uniform="preset")
        card = tk.Frame(
            preset_row, bg=PANEL, padx=10, pady=9,
            highlightthickness=1, highlightbackground=LINE, cursor="hand2",
        )
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))
        radio = tk.Radiobutton(
            card, variable=layout_choice, value=preset.key, text=preset.title,
            bg=PANEL, activebackground=PANEL, fg=TEXT, activeforeground=TEXT,
            selectcolor=RAISED, font=("Segoe UI Semibold", 9), anchor="w",
            takefocus=True, command=lambda key=preset.key: choose_layout(key),
        )
        radio.pack(fill="x")
        canvas = tk.Canvas(card, width=238, height=70, bg="#0f0a06",
                           highlightthickness=0, bd=0, cursor="hand2")
        canvas.pack(fill="x", pady=(6, 7))
        draw_layout_schematic(canvas, preset)
        description = tk.Label(
            card, text=preset.tagline, bg=PANEL, fg=DIM, font=("Segoe UI", 8),
            justify="left", wraplength=225, cursor="hand2",
        )
        description.pack(anchor="w")
        card.bind("<Button-1>", lambda _event, key=preset.key: choose_layout(key))
        canvas.bind("<Button-1>", lambda _event, key=preset.key: choose_layout(key))
        description.bind("<Button-1>", lambda _event, key=preset.key: choose_layout(key))
        preset_cards[preset.key] = (card, radio)

    target_panel = tk.Frame(layout_page, bg=BG)
    tk.Label(target_panel, text="APPLY PRESET TO", bg=BG, fg=GOLD,
             font=("Segoe UI Semibold", 8)).pack(anchor="w", pady=(0, 4))
    target_mode = tk.StringVar(value="existing")
    target_mode_row = tk.Frame(target_panel, bg=BG)
    target_mode_row.pack(fill="x")
    existing_mode = tk.Radiobutton(
        target_mode_row, text="Detected character", variable=target_mode, value="existing",
        bg=BG, activebackground=BG, fg=TEXT, activeforeground=TEXT,
        selectcolor=RAISED, font=("Segoe UI Semibold", 9),
        command=lambda: refresh_target_mode(),
    )
    existing_mode.pack(side="left")
    manual_mode = tk.Radiobutton(
        target_mode_row, text="Character not listed / create target",
        variable=target_mode, value="manual", bg=BG, activebackground=BG,
        fg=TEXT, activeforeground=TEXT, selectcolor=RAISED,
        font=("Segoe UI Semibold", 9), command=lambda: refresh_target_mode(),
    )
    manual_mode.pack(side="left", padx=(18, 0))
    target_var = tk.StringVar()
    target_combo = ttk.Combobox(target_panel, textvariable=target_var, state="disabled")
    target_combo.pack(fill="x", pady=(5, 3), ipady=3)

    manual_fields = tk.Frame(target_panel, bg=BG)
    manual_character = tk.StringVar()
    manual_server = tk.StringVar(value="Qeynos")
    character_column = tk.Frame(manual_fields, bg=BG)
    character_column.pack(side="left", fill="x", expand=True)
    tk.Label(character_column, text="CHARACTER NAME · CASE-SENSITIVE", bg=BG, fg=DIM,
             font=("Segoe UI Semibold", 7)).pack(anchor="w", pady=(0, 3))
    character_entry = tk.Entry(
        character_column, textvariable=manual_character, bg=RAISED, fg=TEXT,
        insertbackground=CYAN, relief="flat", highlightthickness=1,
        highlightbackground=LINE, highlightcolor=CYAN, font=("Segoe UI", 10),
    )
    character_entry.pack(fill="x", ipady=6)
    server_column = tk.Frame(manual_fields, bg=BG)
    server_column.pack(side="left", padx=(8, 0))
    tk.Label(server_column, text="SERVER", bg=BG, fg=DIM,
             font=("Segoe UI Semibold", 7)).pack(anchor="w", pady=(0, 3))
    server_combo = ttk.Combobox(
        server_column, textvariable=manual_server,
        values=[server.display for server in LEGENDS_SERVERS], state="readonly", width=22,
    )
    server_combo.pack(ipady=3)
    layout_column = tk.Frame(manual_fields, bg=BG)
    layout_column.pack(side="left", padx=(8, 0))
    tk.Label(layout_column, text="LAYOUT SLOT", bg=BG, fg=DIM,
             font=("Segoe UI Semibold", 7)).pack(anchor="w", pady=(0, 3))
    tk.Label(layout_column, text="Layout 1", bg=RAISED, fg=GOLD,
             font=("Segoe UI Semibold", 9), padx=10, pady=7).pack()
    manual_preview = tk.Label(target_panel, text="", bg=BG, fg=CYAN,
                              font=("Consolas", 9), anchor="w")
    manual_preview.pack(fill="x", pady=(3, 0))
    target_note = tk.Label(target_panel, text="", bg=BG, fg=DIM,
                           font=("Segoe UI", 9), anchor="w")
    target_note.pack(fill="x")
    target_paths: dict[str, Path] = {}

    # --- Step 3: options and review ---------------------------------------
    review_page = pages[2]
    tk.Label(review_page, text="READY TO INSTALL", bg=BG, fg=GOLD,
             font=("Georgia", 9, "bold")).pack(anchor="w")
    tk.Label(review_page, text="Review every change before it happens.", bg=BG, fg=TEXT,
             font=("Segoe UI Semibold", 18)).pack(anchor="w", pady=(5, 12))

    startup_var = tk.BooleanVar(value=True)
    desktop_var = tk.BooleanVar(value=True)
    options = tk.Frame(
        review_page, bg=PANEL, padx=14, pady=11,
        highlightthickness=1, highlightbackground=LINE,
    )
    options.pack(fill="x")
    startup_check = tk.Checkbutton(
        options, text="Start Loremaster with Windows", variable=startup_var,
        bg=PANEL, activebackground=PANEL, fg=TEXT, activeforeground=TEXT,
        selectcolor=RAISED, font=("Segoe UI Semibold", 10), anchor="w",
    )
    startup_check.pack(fill="x")
    tk.Label(options, text="Waits quietly for eqgame.exe before opening the HUD.",
             bg=PANEL, fg=DIM, font=("Segoe UI", 9)).pack(anchor="w", padx=23)
    desktop_check = tk.Checkbutton(
        options, text="Create a Loremaster desktop shortcut", variable=desktop_var,
        bg=PANEL, activebackground=PANEL, fg=TEXT, activeforeground=TEXT,
        selectcolor=RAISED, font=("Segoe UI Semibold", 10), anchor="w",
    )
    desktop_check.pack(fill="x", pady=(8, 0))
    tk.Label(options, text="The tray icon can restore, hide, or exit Loremaster.",
             bg=PANEL, fg=DIM, font=("Segoe UI", 9)).pack(anchor="w", padx=23)

    review_box = tk.Frame(
        review_page, bg="#100b07", padx=16, pady=12,
        highlightthickness=1, highlightbackground=LINE,
    )
    review_box.pack(fill="x", pady=(12, 0))
    review_var = tk.StringVar()
    tk.Label(review_box, textvariable=review_var, bg="#100b07", fg=TEXT,
             font=("Segoe UI", 9), justify="left", anchor="nw",
             wraplength=790).pack(fill="x")

    progress = ttk.Progressbar(review_page, mode="indeterminate",
                               style="Spin.Horizontal.TProgressbar")
    progress.pack(fill="x", pady=(14, 4))
    status = tk.Label(review_page, text="Ready to install SpinUI.", bg=BG,
                      fg=DIM, font=("Segoe UI", 9), anchor="w")
    status.pack(fill="x")

    footer = tk.Frame(root, bg=PANEL, padx=30, pady=12)
    footer.pack(fill="x", side="bottom")
    install_results: queue.Queue[tuple[str, object]] = queue.Queue()
    installing = {"active": False}

    current_page = {"index": 0}
    installation_done = {"value": False}

    def selected_resolution_profile() -> str:
        profile_key = PROFILE_LABEL_TO_KEY.get(resolution_profile_var.get())
        if profile_key is None:
            raise ValueError("Choose a supported SpinUI screen profile.")
        return profile_key

    def manual_target_path() -> Path:
        token = SERVER_TOKEN_BY_DISPLAY.get(manual_server.get())
        if token is None:
            raise ValueError("Choose one of the supported EverQuest Legends servers.")
        filename = manual_layout_filename(manual_character.get(), token, 1)
        return Path(path_var.get().strip()) / filename

    def selected_target_plan() -> tuple[Path | None, bool]:
        if layout_choice.get() == KEEP_LAYOUT:
            return None, False
        if target_mode.get() == "manual":
            return manual_target_path(), True
        return target_paths.get(target_var.get()), False

    def selected_target() -> Path | None:
        try:
            return selected_target_plan()[0]
        except ValueError:
            return None

    def refresh_manual_preview(*_args) -> None:
        if target_mode.get() != "manual":
            manual_preview.configure(text="")
            return
        try:
            candidate = manual_target_path()
            eq = Path(path_var.get().strip())
            resolved = validate_layout_target(eq, candidate, allow_create=True)
            exists = resolved.exists()
            manual_preview.configure(
                text=(f"EXACT FILE  {resolved.name}" +
                      ("  ·  existing file will be merged" if exists else "  ·  new file")),
                fg=(GOLD if exists else CYAN),
            )
        except (ValueError, OSError):
            manual_preview.configure(
                text="Enter the character's exact name to preview the safe filename.", fg=DIM
            )

    def refresh_target_mode(*_args) -> None:
        if not target_paths and target_mode.get() == "existing":
            target_mode.set("manual")
        using_existing = target_mode.get() == "existing"
        existing_mode.configure(state=("normal" if target_paths else "disabled"))
        if using_existing:
            manual_preview.pack_forget()
            if not target_combo.winfo_manager():
                target_combo.pack(fill="x", pady=(5, 3), ipady=3, before=target_note)
            target_combo.configure(state=("readonly" if target_paths else "disabled"))
            manual_fields.pack_forget()
            target_note.configure(
                text=("Window positions, sizes, visibility, and chat routing are merged. "
                      "A timestamped backup is created when anything changes."), fg=CYAN,
            )
        else:
            target_combo.pack_forget()
            manual_fields.pack(fill="x", pady=(5, 0), before=target_note)
            if not manual_preview.winfo_manager():
                manual_preview.pack(fill="x", pady=(3, 0), before=target_note)
            refresh_manual_preview()
            target_note.configure(
                text=("If that INI already exists, it is detected again at install time and "
                      "merged safely; otherwise the selected preset creates it."), fg=DIM,
            )

    def refresh_layout_selection(*_args) -> None:
        selected = layout_choice.get()
        keep_card.configure(highlightbackground=(CYAN if selected == KEEP_LAYOUT else LINE))
        for key, (card, radio) in preset_cards.items():
            radio.configure(state="normal")
            card.configure(highlightbackground=(CYAN if selected == key else LINE))
        if selected == KEEP_LAYOUT:
            target_panel.pack_forget()
        else:
            if not target_panel.winfo_manager():
                target_panel.pack(fill="x", pady=(12, 0))
            refresh_target_mode()

    def profile_selected(_event=None) -> None:
        profile_selection_touched["value"] = True
        refresh_layout_selection()
        if current_page["index"] == 2:
            update_review()

    def refresh_installation(*_args):
        nonlocal target_paths
        eq = Path(path_var.get().strip())
        layouts = character_layouts(eq) if is_eq_root(eq) else []
        target_paths = {character_layout_label(path): path for path in layouts}
        labels = list(target_paths)
        target_combo["values"] = labels
        if target_var.get() not in target_paths:
            target_var.set(labels[0] if labels else "")
        valid = is_eq_root(eq)
        detect.configure(
            text=("Ready · eqgame.exe found" if valid else "Choose the folder containing eqgame.exe"),
            fg=(CYAN if valid else DIM),
        )
        detected_resolution = detect_client_resolution(eq) if valid else None
        resolution_hint.configure(text=resolution_note(detected_resolution))
        if valid and not profile_selection_touched["value"]:
            recommended = recommended_resolution_profile(detected_resolution)
            resolution_profile_var.set(recommended.label)
        if labels and target_mode.get() not in {"existing", "manual"}:
            target_mode.set("existing")
        elif not labels:
            target_mode.set("manual")
        refresh_layout_selection()

    def choose_folder(_event=None):
        selected = filedialog.askdirectory(title="Choose the folder containing eqgame.exe")
        if selected:
            path_var.set(selected)
            refresh_installation()

    def update_review() -> None:
        eq = Path(path_var.get().strip())
        choice = layout_choice.get()
        if choice == KEEP_LAYOUT:
            review_var.set(
                f"EVERQUEST       {eq}\n\n"
                "WILL CHANGE     Install or refresh the SpinUI skin and Loremaster\n"
                "WILL PRESERVE   Every character INI and all existing window positions\n"
                "LAYOUT          Keep Existing · no character-layout write or backup"
            )
            return
        preset = LAYOUT_PRESETS[choice]
        profile = RESOLUTION_PROFILES[selected_resolution_profile()]
        try:
            requested, allow_create = selected_target_plan()
            target = validate_layout_target(eq, requested, allow_create=allow_create)
        except (ValueError, OSError) as exc:
            review_var.set(f"LAYOUT SELECTION NEEDS ATTENTION\n{exc}")
            return
        if target.exists():
            layout_action = (
                f"Apply {preset.title.title()} · {profile.width}×{profile.height} "
                f"to {target.name}")
            backup_copy = "Create a timestamped byte-exact backup when values change"
            preserve_copy = "Locks · click-through · hotbar/spell data · loadouts"
            preserve_extra = "Unknown and client-added settings in every other section"
        else:
            layout_action = (
                f"Create {target.name} from {preset.title.title()} · "
                f"{profile.width}×{profile.height}")
            backup_copy = "No backup needed because the character INI is new"
            preserve_copy = "All other character files, hotbuttons, and client settings"
            preserve_extra = "No existing character INI is overwritten"
        review_var.set(
            f"EVERQUEST       {eq}\n\n"
            f"WILL CHANGE     {layout_action}\n"
            f"                Set UISkin, window layout, visibility, and chat routing\n"
            f"BACKUP          {backup_copy}\n"
            f"WILL PRESERVE   {preserve_copy}\n"
            f"                {preserve_extra}\n"
            "LOREMASTER      Install/update while preserving its config and records"
        )

    def show_page(index: int) -> None:
        current_page["index"] = index
        for page in pages:
            page.pack_forget()
        pages[index].pack(fill="both", expand=True)
        for step_index, label in enumerate(step_labels):
            label.configure(
                fg=(CYAN if step_index == index else GOLD_BRIGHT if step_index < index else DIM)
            )
        back_button.configure(state=("disabled" if index == 0 else "normal"))
        primary_button.configure(text=("INSTALL SPINUI" if index == 2 else "CONTINUE"))
        if index == 1:
            refresh_installation()
        elif index == 2:
            update_review()

    def continue_or_install() -> None:
        if installation_done["value"]:
            root.destroy()
            return
        index = current_page["index"]
        if index == 0:
            refresh_installation()
            if not is_eq_root(Path(path_var.get().strip())):
                messagebox.showerror(
                    "EverQuest not found", "Choose the folder containing eqgame.exe."
                )
                path_entry.focus_set()
                return
            show_page(1)
            return
        if index == 1:
            if layout_choice.get() != KEEP_LAYOUT:
                try:
                    requested, allow_create = selected_target_plan()
                    target = validate_layout_target(
                        Path(path_var.get().strip()), requested,
                        allow_create=allow_create,
                    )
                    source = resolve_layout_source(
                        payload,
                        layout_choice.get(),
                        selected_resolution_profile(),
                    )
                    prepare_layout_update(source, target, allow_create=allow_create)
                except (ValueError, FileNotFoundError, OSError) as exc:
                    messagebox.showerror("Character layout required", str(exc))
                    if target_mode.get() == "manual":
                        character_entry.focus_set()
                    return
            show_page(2)
            return
        begin_install()

    def go_back() -> None:
        if installing["active"] or current_page["index"] == 0:
            return
        show_page(current_page["index"] - 1)

    back_button = flat_button(footer, "BACK", go_back)
    back_button.pack(side="left")
    primary_button = flat_button(footer, "CONTINUE", continue_or_install, primary=True)
    primary_button.pack(side="right")

    def finish_success(lines: list[str]):
        installing["active"] = False
        installation_done["value"] = True
        progress.stop()
        back_button.configure(state="disabled")
        primary_button.configure(state="normal", text="CLOSE")
        status.configure(text="Installed successfully.", fg=CYAN)
        messagebox.showinfo("SpinUI installed", "SpinUI is ready.\n\n" + "\n".join(lines))

    def finish_error(exc: Exception):
        installing["active"] = False
        progress.stop()
        back_button.configure(state="normal")
        primary_button.configure(state="normal", text="INSTALL SPINUI")
        status.configure(text=str(exc), fg="#de3e48")
        messagebox.showerror("Installation could not finish", str(exc))

    def begin_install(_event=None):
        if installing["active"]:
            return
        eq = Path(path_var.get().strip())
        if not is_eq_root(eq):
            messagebox.showerror("EverQuest not found", "Choose the folder containing eqgame.exe.")
            return
        choice = layout_choice.get()
        should_install_layout = choice != KEEP_LAYOUT
        chosen_resolution_profile = selected_resolution_profile()
        target = None
        create_target = False
        if should_install_layout:
            try:
                requested, create_target = selected_target_plan()
                target = validate_layout_target(
                    eq, requested, allow_create=create_target
                )
                source = resolve_layout_source(
                    payload, choice, chosen_resolution_profile)
                prepare_layout_update(source, target, allow_create=create_target)
            except (ValueError, FileNotFoundError, OSError) as exc:
                finish_error(exc)
                return
        should_run_at_startup = startup_var.get()
        should_create_desktop_shortcut = desktop_var.get()
        back_button.configure(state="disabled")
        primary_button.configure(state="disabled", text="INSTALLING…")
        status.configure(text="Copying the UI and configuring Loremaster…", fg=DIM)
        progress.start(12)
        installing["active"] = True

        def worker():
            try:
                lines = install_payload(
                    payload, eq, install_layout=should_install_layout, layout_target=target,
                    run_at_startup=should_run_at_startup,
                    desktop_shortcut=should_create_desktop_shortcut,
                    replace_running=True, require_eq_closed=True,
                    layout_preset=(choice if should_install_layout else None),
                    resolution_profile=chosen_resolution_profile,
                    create_layout_target=create_target,
                )
            except Exception as exc:  # surfaced in a native message box
                install_results.put(("error", exc))
            else:
                install_results.put(("ok", lines))

        threading.Thread(target=worker, daemon=True).start()
        root.after(100, poll_install_result)

    def poll_install_result():
        try:
            outcome, value = install_results.get_nowait()
        except queue.Empty:
            if installing["active"]:
                root.after(100, poll_install_result)
            return
        if outcome == "ok":
            finish_success(value)
        else:
            finish_error(value)

    def request_close():
        if installing["active"]:
            messagebox.showinfo(
                "Installation in progress",
                "SpinUI is still being installed. This window will be ready to close in a moment.",
            )
            return
        root.destroy()

    layout_choice.trace_add("write", refresh_layout_selection)
    profile_combo.bind("<<ComboboxSelected>>", profile_selected)
    target_mode.trace_add("write", refresh_target_mode)
    manual_character.trace_add("write", refresh_manual_preview)
    manual_server.trace_add("write", refresh_manual_preview)
    startup_var.trace_add("write", lambda *_args: update_review() if current_page["index"] == 2 else None)
    desktop_var.trace_add("write", lambda *_args: update_review() if current_page["index"] == 2 else None)
    path_entry.bind("<FocusOut>", refresh_installation)
    path_entry.bind("<Return>", lambda _event: continue_or_install())
    root.bind("<Escape>", lambda _event: request_close())
    root.protocol("WM_DELETE_WINDOW", request_close)

    roots = find_eq_roots()
    if roots:
        path_var.set(str(roots[0]))
        detect.configure(text=f"Auto-detected {roots[0]}", fg=CYAN)
    refresh_installation()
    show_page(0)
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--selftest", action="store_true",
                        help="Run the installer's internal test suite and exit.")
    parser.add_argument("--install", action="store_true",
                        help="Install SpinUI from the command line, without the GUI.")
    parser.add_argument("--eq-dir", type=Path, default=None,
                        help="EverQuest folder containing eqgame.exe. Auto-detected if omitted, "
                             "including Wine/Proton prefixes on Linux.")
    parser.add_argument("--skin", choices=AVAILABLE_SKINS, default=SKIN_NAME,
                        help=f"Skin to install (default: {SKIN_NAME}).")
    parser.add_argument("--layout", choices=sorted(LAYOUT_PRESETS), default=None,
                        help="Apply a layout preset. Omit to keep the existing character layout.")
    parser.add_argument("--resolution", choices=sorted(RESOLUTION_PROFILES),
                        default=DEFAULT_RESOLUTION_PROFILE,
                        help=f"Screen profile used with --layout (default: {DEFAULT_RESOLUTION_PROFILE}).")
    parser.add_argument("--layout-target", default=None,
                        help="Existing UI_<Character>_<Server>_LO#.ini filename inside --eq-dir.")
    parser.add_argument("--character", default=None,
                        help="Character name for a manual/new layout target (use with --server).")
    parser.add_argument("--server", choices=[server.token for server in LEGENDS_SERVERS],
                        default=None, help="Server token for --character.")
    parser.add_argument("--create-layout", action="store_true",
                        help="Create the --character/--server (or --layout-target) INI if missing.")
    parser.add_argument("--startup-shortcut", action="store_true",
                        help="Register Loremaster to start automatically "
                             "(Windows Startup folder, or XDG autostart on Linux).")
    parser.add_argument("--desktop-shortcut", action="store_true",
                        help="Create a Loremaster desktop shortcut (.lnk on Windows, "
                             ".desktop on Linux).")
    parser.add_argument("--replace-running", action="store_true",
                        help="Close a previously installed, currently running Loremaster first.")
    parser.add_argument("--allow-running", action="store_true",
                        help="Skip the safety check that refuses to install while eqgame.exe "
                             "is running (installing over a live client can corrupt UI files).")
    parser.add_argument("--list-presets", action="store_true",
                        help="List available layout presets, resolution profiles, and skins, "
                             "then exit.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and report the install plan without writing anything; "
                             "implies --install.")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    if args.list_presets:
        return _print_presets()
    if args.install or args.dry_run:
        return _cli_install(args)
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
