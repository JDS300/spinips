#!/usr/bin/env python3
"""Prove that SpinUI Glass is complete, current, and binding-safe.

The Glass skin is allowed to change presentation only.  This audit compares
the parsed XML trees after removing the explicitly permitted color and atlas
differences, then checks the generated textures for expected dimensions,
transparency, palette cues, and meaningful visual divergence from Reloaded.
"""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from build_spinui_glass import CONTROL_ATLAS, CONTROL_NAMES
from spinui_glass_theme import ICE, MINT, VIOLET


REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "spinui_reloaded"
GLASS = REPO / "spinui_glass"
VISUAL_COLOR_TAGS = {
    "TextColor", "DisabledColor", "HighlightColor", "SelectedColor",
}
REQUIRED_DIFFERENCES = (
    "wnd_bg_light_rock.tga",
    "wnd_bg_dark_rock.tga",
    "wnd_bg_light_rock_inner.tga",
    "window_pieces01.tga",
    "window_pieces05.tga",
    "window_pieces09.tga",
    "default_spellbook01.tga",
    "default_spellbook02.tga",
)


class AuditFailure(RuntimeError):
    pass


def fail(message: str) -> None:
    raise AuditFailure(message)


def xml_files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*.xml")
        if path.is_file()
    }


def normalized_node(
    node: ET.Element,
    *,
    filename: str,
    owner: str = "",
) -> tuple | None:
    """Return a semantic tree with only approved Glass changes ignored."""
    if node.tag in VISUAL_COLOR_TAGS:
        return None

    item = node.get("item", "")
    current_owner = item or owner
    if (
        filename.casefold() == "equi_animations.xml"
        and node.tag == "TextureInfo"
        and item.casefold() == CONTROL_ATLAS.casefold()
    ):
        return None

    text = (node.text or "").strip()
    if (
        filename.casefold() == "equi_animations.xml"
        and node.tag == "Texture"
        and current_owner in CONTROL_NAMES
    ):
        text = "<glass-control-atlas>"
    elif filename.casefold() == "equi_spellbookwnd.xml" and node.tag == "MenuName":
        text = "<spellbook-display-name>"

    children = []
    for child in node:
        normalized = normalized_node(
            child, filename=filename, owner=current_owner)
        if normalized is not None:
            children.append(normalized)
    return node.tag, tuple(sorted(node.attrib.items())), text, tuple(children)


def check_xml_parity() -> tuple[int, int]:
    source_files = xml_files(SOURCE)
    glass_files = xml_files(GLASS)
    if set(source_files) != set(glass_files):
        missing = sorted(set(source_files) - set(glass_files))
        extra = sorted(set(glass_files) - set(source_files))
        fail(
            "Glass XML manifest differs from Reloaded: "
            f"missing={missing[:8]} extra={extra[:8]}"
        )

    binding_count = 0
    for relative in sorted(source_files):
        try:
            source_root = ET.parse(source_files[relative]).getroot()
            glass_root = ET.parse(glass_files[relative]).getroot()
        except ET.ParseError as exc:
            fail(f"cannot parse {relative}: {exc}")
        if normalized_node(source_root, filename=relative) != normalized_node(
            glass_root, filename=relative
        ):
            fail(f"non-visual XML drift in {relative}")

        def bindings(root: ET.Element) -> set[tuple[str, str, str, str]]:
            return {
                (node.tag, node.get("item", ""),
                 node.findtext("ScreenID") or "", node.findtext("EQType") or "")
                for node in root.iter()
                if node.get("item")
                and not (
                    node.tag == "TextureInfo"
                    and node.get("item", "").casefold() == CONTROL_ATLAS.casefold()
                )
            }

        source_bindings = bindings(source_root)
        glass_bindings = bindings(glass_root)
        if source_bindings != glass_bindings:
            fail(f"ScreenID/EQType binding drift in {relative}")
        binding_count += len(source_bindings)
    return len(source_files), binding_count


def check_builder_current() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "build_spinui_glass.py"), "--check"],
        cwd=REPO,
        check=False,
    )
    if result.returncode:
        fail("generated Glass payload is stale; run tools/build_spinui_glass.py")


def check_control_registry() -> int:
    root = ET.parse(GLASS / "EQUI_Animations.xml").getroot()
    texture_info = next(
        (node for node in root.findall("TextureInfo")
         if node.get("item", "").casefold() == CONTROL_ATLAS.casefold()),
        None,
    )
    if texture_info is None:
        fail(f"EQUI_Animations.xml does not declare {CONTROL_ATLAS}")
    declared_size = (
        int(texture_info.findtext("Size/CX") or 0),
        int(texture_info.findtext("Size/CY") or 0),
    )
    actual_size = image(GLASS / CONTROL_ATLAS).size
    if declared_size != actual_size:
        fail(
            f"{CONTROL_ATLAS} registry size {declared_size} does not match "
            f"the atlas {actual_size}"
        )

    animations = {
        node.get("item", ""): (node.findtext("Frames/Texture") or "").strip()
        for node in root.findall("Ui2DAnimation")
    }
    wrong = [
        name for name in CONTROL_NAMES
        if animations.get(name, "").casefold() != CONTROL_ATLAS.casefold()
    ]
    if wrong:
        fail(
            f"Glass control animations do not use {CONTROL_ATLAS}: "
            + ", ".join(wrong[:8])
        )
    return len(CONTROL_NAMES)


def image(path: Path) -> Image.Image:
    try:
        return Image.open(path).convert("RGBA")
    except (OSError, ValueError) as exc:
        fail(f"cannot read texture {path.relative_to(REPO)}: {exc}")


def contains_color(paths: tuple[Path, ...], wanted: tuple[int, int, int]) -> bool:
    for path in paths:
        candidate = image(path)
        pixels = candidate.load()
        for y in range(candidate.height):
            for x in range(candidate.width):
                red, green, blue, alpha = pixels[x, y]
                if alpha and max(abs(red - wanted[0]), abs(green - wanted[1]),
                                 abs(blue - wanted[2])) <= 5:
                    return True
    return False


def check_texture_system() -> int:
    for name in REQUIRED_DIFFERENCES:
        source = SOURCE / name
        glass = GLASS / name
        if not source.is_file() or not glass.is_file():
            fail(f"missing required Glass texture pair: {name}")
        if source.read_bytes() == glass.read_bytes():
            fail(f"Glass texture is unchanged from Reloaded: {name}")
        if image(source).size != image(glass).size:
            fail(f"Glass texture dimensions changed: {name}")

    control = image(GLASS / CONTROL_ATLAS)
    source_controls = image(SOURCE / "window_pieces11a.dds")
    if control.size != source_controls.size:
        fail(
            f"{CONTROL_ATLAS} is {control.size}, expected {source_controls.size}"
        )
    alpha_min, alpha_max = control.getextrema()[3]
    if alpha_min != 0 or alpha_max < 200:
        fail(f"{CONTROL_ATLAS} lacks transparent and opaque control states")

    background_names = (
        "wnd_bg_light_rock.tga",
        "wnd_bg_dark_rock.tga",
        "wnd_bg_light_rock_inner.tga",
    )
    for name in background_names:
        minimum, maximum = image(GLASS / name).getextrema()[3]
        if minimum >= 245 or maximum >= 250:
            fail(f"{name} is not a controlled translucent Glass surface")

    palette_paths = tuple(
        GLASS / name for name in (
            "window_pieces01.tga", "window_pieces05.tga",
            "spin_glass_controls.tga", "default_spellbook01.tga",
        )
    )
    for label, color in (("ice", ICE), ("mint", MINT), ("violet", VIOLET)):
        if not contains_color(palette_paths, color):
            fail(f"Glass texture system has no visible {label} palette cue")

    return len(REQUIRED_DIFFERENCES) + 1


def main() -> int:
    try:
        check_builder_current()
        xml_count, binding_count = check_xml_parity()
        control_count = check_control_registry()
        texture_count = check_texture_system()
    except AuditFailure as exc:
        print(f"SpinUI Glass audit: FAIL\n{exc}", file=sys.stderr)
        return 1
    print(
        "SpinUI Glass audit: PASS | "
        f"XML {xml_count} | bindings {binding_count} | "
        f"controls {control_count} | key textures {texture_count} | "
        "deterministic payload"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
