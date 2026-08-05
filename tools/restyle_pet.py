#!/usr/bin/env python3
"""Make every SpinUI pet layout deterministic, readable, and clickable.

EverQuest subtracts rounded-frame insets before flowing a TileLayoutBox. The
old 84px four-column command grid fit the XML width by only four pixels, so the
Legends client wrapped it to three columns and pushed Inventory plus later
native commands below the clickable panel. Legends places these command
buttons directly; SpinUI now does the same while retaining every native
ScreenID and allowing Legends to inject each label/action.

The compact geometry keeps the proven 356px-wide command panel intact while
compressing its vertical rhythm to 155px. Beneath it
the fixed default seats a two-row rail of 24px effect cells - 28 positions,
more than a pet carries - with each countdown drawn on its own icon, so the
window stays low-profile. Resizable top/bottom variants open at the same rail
and grow the buff region, not the command panel, when more rows are wanted;
the right-rail variant grows in both directions from its own 441x181 because
its unchanged vertical effect rail determines that variant's minimum height.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKIN = REPO / "spinui_reloaded"
VARIANTS = tuple(SKIN / f"EQUI_PetInfoWindow{suffix}.xml"
                 for suffix in ("", "1", "2", "3"))

BUTTON_SIZE = (78, 20)

# --- Companion effect rail -------------------------------------------------
# A pet effect cell carries two client-drawn overlays that the skin cannot
# separate: the remaining-duration countdown, centered on the cell, and the
# beneficial/detrimental background (an 8px solid blue or red tile) stretched
# to fill it.  One cell width controls both.  A cell wide enough to give the
# countdown its own column therefore also stretches that tile into a slab of
# flat blue per effect, which costs far more than the column buys - so cells
# stay icon sized, the tile stays a frame around the art, and the countdown
# rides on the icon in shadowed ember gold.
BUFF_CELL = (24, 24)
BUFF_DECAL = ((22, 22), (1, 1))
BUFF_CELLS = {name: BUFF_CELL for name in (
    "EQUI_PetInfoWindow.xml", "EQUI_PetInfoWindow1.xml",
    "EQUI_PetInfoWindow2.xml", "EQUI_PetInfoWindow3.xml")}
BUFF_DECALS = {name: BUFF_DECAL for name in BUFF_CELLS}
# A cell may not extend past its icon by more than this, or the background
# tile stops reading as a frame and becomes a slab.
BUFF_PLATE_BLEED = 2
BUFF_TIMER_FONT = 3
# EverQuest subtracts a bordered host's frame insets before it flows a
# TileLayoutBox, so every rail is sized for its rows *plus* this much on both
# axes.  Too little and the client silently drops a row or a column.
BUFF_BORDER_INSET = 8
COMMAND_POSITIONS = {
    **{
        index: (10 + (index % 4) * 84, 64 + (index // 4) * 21)
        for index in range(12)
    },
    12: (94, 127),
    13: (178, 127),
}
COMMAND_ITEMS = tuple(f"PIW_Pet{i}_Button" for i in range(14))
# Ember gold, matching the Spell/Song Effects countdowns, so a timer never
# reads as part of the effect art it sits beside.
TIMER_COLOR = (248, 214, 140)
PET_PANEL_SIZE = (356, 155)
# Two 24px rows seat 28 effect positions - comfortably more than a pet carries
# - in 58px of rail, so the fixed default stays a low-profile command center
# instead of a tall panel.
WINDOW_SIZES = {
    "EQUI_PetInfoWindow.xml": (356, 210),
    "EQUI_PetInfoWindow1.xml": (356, 210),
    "EQUI_PetInfoWindow2.xml": (356, 210),
    "EQUI_PetInfoWindow3.xml": (441, 181),
}
BUFF_RECTS = {
    "EQUI_PetInfoWindow.xml": (4, 152, 352, 208),
    "EQUI_PetInfoWindow1.xml": (4, 152, 352, 208),
    "EQUI_PetInfoWindow2.xml": (4, 2, 352, 58),
    "EQUI_PetInfoWindow3.xml": (353, 2, 437, 179),
}
SUBWINDOW_RECTS = {
    "EQUI_PetInfoWindow.xml": (0, 0, 356, 155),
    "EQUI_PetInfoWindow1.xml": (0, 0, 356, 155),
    "EQUI_PetInfoWindow2.xml": (0, 55, 356, 210),
    "EQUI_PetInfoWindow3.xml": (0, 0, 356, 155),
}
BUFF_CAPACITY = {
    "EQUI_PetInfoWindow.xml": 28,
    "EQUI_PetInfoWindow1.xml": 28,
    "EQUI_PetInfoWindow2.xml": 28,
    "EQUI_PetInfoWindow3.xml": 21,
}


def _item_block(text: str, tag: str, item_name: str) -> tuple[re.Match[str], str]:
    pattern = re.compile(
        rf'(<{tag} item="{re.escape(item_name)}">)(.*?)(</{tag}>)', re.S)
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"missing {tag} {item_name}")
    return match, match.group(2)


def _replace_item(text: str, tag: str, item_name: str, body: str) -> str:
    match, _ = _item_block(text, tag, item_name)
    return text[:match.start()] + match.group(1) + body + match.group(3) + text[match.end():]


def _set_scalar(body: str, field: str, value: str) -> str:
    pattern = re.compile(rf'(<{field}>)[^<]*(</{field}>)')
    body, count = pattern.subn(rf'\g<1>{value}\g<2>', body, count=1)
    if count != 1:
        raise ValueError(f"missing field {field}")
    return body


def _set_item_fields(
        text: str, tag: str, item_name: str, fields: dict[str, object]) -> str:
    _, body = _item_block(text, tag, item_name)
    for field, value in fields.items():
        body = _set_scalar(body, field, str(value).lower()
                           if isinstance(value, bool) else str(value))
    return _replace_item(text, tag, item_name, body)


def _set_button(text: str, index: int) -> str:
    item_name = COMMAND_ITEMS[index]
    _, body = _item_block(text, "Button", item_name)
    location = (
        "\n\t\t<Location>\n"
        f"\t\t\t<X>{COMMAND_POSITIONS[index][0]}</X>\n"
        f"\t\t\t<Y>{COMMAND_POSITIONS[index][1]}</Y>\n"
        "\t\t</Location>"
    )
    location_pattern = re.compile(
        r'\s*<Location>.*?</Location>[ \t]*', re.S)
    if location_pattern.search(body):
        body = location_pattern.sub(location, body, count=1)
    else:
        anchor = "\n\t\t<RelativePosition>true</RelativePosition>"
        if anchor not in body:
            raise ValueError(f"missing RelativePosition in {item_name}")
        body = body.replace(anchor, anchor + location, 1)
    body = _set_scalar(body, "CX", str(BUTTON_SIZE[0]))
    body = _set_scalar(body, "CY", str(BUTTON_SIZE[1]))
    return _replace_item(text, "Button", item_name, body)


def _direct_command_pieces(text: str) -> str:
    match, body = _item_block(text, "Screen", "PetInfoSubWindow")
    direct = "\n".join(f"\t\t<Pieces>{name}</Pieces>" for name in COMMAND_ITEMS)
    tile_piece = "\t\t<Pieces>TileLayoutBox:PIW_PetButtons</Pieces>"
    existing = [
        node for node in re.findall(r'<Pieces>([^<]+)</Pieces>', body)
        if node in COMMAND_ITEMS
    ]
    if tile_piece in body:
        body = re.sub(
            r'\t\t<Pieces>TileLayoutBox:PIW_PetButtons</Pieces>[ \t]*',
            direct,
            body,
            count=1,
        )
    elif existing != list(COMMAND_ITEMS):
        raise ValueError("pet subwindow lost its native command pieces")
    body = re.sub(
        r'(<Pieces>PIW_Pet\d+_Button</Pieces>)[ \t]+', r'\1', body)
    return text[:match.start()] + match.group(1) + body + match.group(3) + text[match.end():]


def _remove_flow_grid(text: str) -> str:
    pattern = re.compile(
        r'\n\t<TileLayoutBox item="PIW_PetButtons">.*?</TileLayoutBox>\s*', re.S)
    return pattern.sub("\n\t", text, count=1)


def _polish_buff_host(text: str) -> str:
    _, body = _item_block(text, "Screen", "PIW_BuffWindow")
    # Opaque recessed well (WDT_Inner) so active effects sit on a clean
    # obsidian inset instead of loose tiles over the window background.  The
    # well also carries its own thin frame: that frame is what divides commands
    # from effects now that the command panel no longer paints a border of its
    # own, and unlike the panel's border it sits inside the window instead of
    # doubling up on the outer frame's corner.  BUFF_BORDER_INSET pays for the
    # pixels the client takes off a bordered host before it flows the tiles.
    body = _set_scalar(body, "Style_Transparent", "false")
    body = _set_scalar(body, "Style_Border", "true")
    return _replace_item(text, "Screen", "PIW_BuffWindow", body)


def _style_buff_chip(text: str, filename: str) -> str:
    """Give each effect cell a readable countdown instead of a stamped icon."""
    cell = BUFF_CELLS[filename]
    decal_size, decal_offset = BUFF_DECALS[filename]
    _, body = _item_block(text, "Button", "PIW_PetBuff_Template")
    body = _set_scalar(body, "Font", BUFF_TIMER_FONT)
    body = _set_scalar(body, "FontShadow", "true")

    def _pair(container: str, cx: int, cy: int) -> None:
        nonlocal body
        pattern = re.compile(
            rf"(<{container}>)(.*?)(</{container}>)", re.S)
        match = pattern.search(body)
        if match is None:
            raise ValueError(f"missing {container} in pet buff template")
        inner = match.group(2)
        first, second = ("CX", "CY") if container.endswith("Size") else ("X", "Y")
        inner = _set_scalar(inner, first, str(cx))
        inner = _set_scalar(inner, second, str(cy))
        body = (body[:match.start()] + match.group(1) + inner
                + match.group(3) + body[match.end():])

    _pair("Size", *cell)
    _pair("DecalSize", *decal_size)
    _pair("DecalOffset", *decal_offset)
    swatch = "".join(
        f"\t\t\t<{channel}>{value}</{channel}>\n"
        for channel, value in zip("RGB", TIMER_COLOR))
    block = f"\t\t<TextColor>\n{swatch}\t\t</TextColor>"
    if "<TextColor>" in body:
        body = re.sub(r"[ \t]*<TextColor>.*?</TextColor>", block, body,
                      count=1, flags=re.S)
    else:
        anchor = "\n\t\t<FontShadow>true</FontShadow>"
        if anchor not in body:
            raise ValueError("pet buff template lost its FontShadow anchor")
        body = body.replace(anchor, f"{anchor}\n{block}", 1)
    return _replace_item(text, "Button", "PIW_PetBuff_Template", body)


def _clean_subwindow_chrome(text: str) -> str:
    """Stop the command panel painting a second window frame.

    PetInfoSubWindow is a panel nested at the outer window's own top-left
    corner, and it carried a titlebar-less window's help/close/minimize
    controls plus its own rounded border.  The client drew that border on top
    of the outer window's identical border and still reserved the minimize
    control at the corner, which read as a mismatched patch that did not fit
    the frame.  The outer window now owns the frame and background; the
    recessed effect well is the divider between commands and effects.
    """
    _, body = _item_block(text, "Screen", "PetInfoSubWindow")
    for field in ("Style_Qmarkbox", "Style_Closebox", "Style_Minimizebox",
                  "Style_Border"):
        body = _set_scalar(body, field, "false")
    body = _set_scalar(body, "Style_Transparent", "true")
    return _replace_item(text, "Screen", "PetInfoSubWindow", body)


def _frame_outer_window(text: str) -> str:
    """Give the outer host window a real frame.

    The buff rail mounts on the outer PetInfoWindow, which the stock skin
    left transparent — so active pet buffs rendered as loose dark tiles
    floating outside the visible command panel. The command subpanel keeps
    its own border, which reads as the divider between commands and effects.
    """
    _, body = _item_block(text, "Screen", "PetInfoWindow")
    body = _set_scalar(body, "Style_Transparent", "false")
    body = _set_scalar(body, "DrawTemplate", "WDT_RoundedNoTitle")
    return _replace_item(text, "Screen", "PetInfoWindow", body)


def _compact_status_rows(text: str) -> str:
    """Tighten the two gauges without sacrificing their labels or indicator."""
    for item_name in ("PIW_PetHPGauge", "PIW_PetHPGauge_NameOnly"):
        text = _set_item_fields(text, "Gauge", item_name, {
            "TopAnchorOffset": 20,
            "BottomAnchorOffset": 39,
        })
    text = _set_item_fields(text, "Label", "PIW_PetHPGaugeLabel", {
        "TopAnchorOffset": 20,
        "BottomAnchorOffset": 39,
    })
    for item_name in ("PIW_PetTargetHPGauge", "PIW_PetTargetHPGauge_NameOnly"):
        text = _set_item_fields(text, "Gauge", item_name, {
            "TopAnchorOffset": 41,
            "BottomAnchorOffset": 60,
        })
    text = _set_item_fields(text, "Label", "PIW_PetTargetHPGaugeLabel", {
        "TopAnchorOffset": 41,
        "BottomAnchorOffset": 60,
    })
    text = _set_item_fields(text, "StaticAnimation", "PetTarget_Indicator", {
        "Y": 39,
    })
    return text


def _compact_geometry(text: str, filename: str) -> str:
    """Apply the minimum polished geometry for one Legends menu variant."""
    width, height = WINDOW_SIZES[filename]
    text = _set_item_fields(
        text, "Screen", "PetInfoWindow", {"CX": width, "CY": height})

    if filename == "EQUI_PetInfoWindow.xml":
        # Fixed default: a 356px command panel with the unchanged two-row
        # effect strip beneath it—no side rail or wasted vertical padding.
        # The resizable variants remain the home for more rows.
        text = _set_item_fields(text, "Screen", "PetInfoWindow", {
            "MenuName": "Fixed Size - Buffs on Bottom",
        })
        text = _set_item_fields(text, "Screen", "PetInfoSubWindow", {
            "TopAnchorOffset": 0,
            "BottomAnchorOffset": 155,
            "RightAnchorOffset": 356,
            "TopAnchorToTop": True,
            "BottomAnchorToTop": True,
            "RightAnchorToLeft": True,
        })
        text = _set_item_fields(text, "Screen", "PIW_BuffWindow", {
            "LeftAnchorOffset": 4,
            "TopAnchorOffset": 152,
            "RightAnchorOffset": 4,
            "BottomAnchorOffset": 2,
            "LeftAnchorToLeft": True,
            "TopAnchorToTop": True,
            "BottomAnchorToTop": False,
        })
        text = _set_item_fields(text, "DragBox", "PIWDragBox1", {
            "TopAnchorOffset": 0,
            "BottomAnchorOffset": 24,
            "RightAnchorOffset": 356,
            "TopAnchorToTop": True,
            "BottomAnchorToTop": True,
            "RightAnchorToLeft": True,
        })
    elif filename == "EQUI_PetInfoWindow1.xml":
        # Bottom: pin the command panel at 155px; extra height adds buff rows.
        text = _set_item_fields(text, "Screen", "PetInfoWindow", {
            "MinVSize": height,
            "MaxHSize": width,
        })
        text = _set_item_fields(text, "Screen", "PetInfoSubWindow", {
            "TopAnchorOffset": 0,
            "BottomAnchorOffset": 155,
            "TopAnchorToTop": True,
            "BottomAnchorToTop": True,
        })
        text = _set_item_fields(text, "Screen", "PIW_BuffWindow", {
            "TopAnchorOffset": 152,
            "BottomAnchorOffset": 2,
            "TopAnchorToTop": True,
            "BottomAnchorToTop": False,
        })
    elif filename == "EQUI_PetInfoWindow2.xml":
        # Top: pin the command panel to the bottom; added height grows buffs.
        text = _set_item_fields(text, "Screen", "PetInfoWindow", {
            "MinVSize": height,
            "MaxHSize": width,
        })
        text = _set_item_fields(text, "Screen", "PetInfoSubWindow", {
            "TopAnchorOffset": 155,
            "BottomAnchorOffset": 0,
            "TopAnchorToTop": False,
            "BottomAnchorToTop": False,
        })
        text = _set_item_fields(text, "Screen", "PIW_BuffWindow", {
            "TopAnchorOffset": 2,
            "BottomAnchorOffset": 152,
            "TopAnchorToTop": True,
            "BottomAnchorToTop": False,
        })
        text = _set_item_fields(text, "DragBox", "PIWDragBox1", {
            "TopAnchorOffset": 155,
            "BottomAnchorOffset": 137,
            "TopAnchorToTop": False,
            "BottomAnchorToTop": False,
        })
    elif filename == "EQUI_PetInfoWindow3.xml":
        # Right: the compact command panel sits beside the unchanged vertical
        # buff rail; that rail owns the variant's taller minimum size.
        text = _set_item_fields(text, "Screen", "PetInfoWindow", {
            "MinHSize": 441,
            "MinVSize": 181,
        })
        text = _set_item_fields(text, "Screen", "PetInfoSubWindow", {
            "TopAnchorOffset": 0,
            "BottomAnchorOffset": 155,
            "RightAnchorOffset": 356,
            "TopAnchorToTop": True,
            "BottomAnchorToTop": True,
            "RightAnchorToLeft": True,
        })
        text = _set_item_fields(text, "Screen", "PIW_BuffWindow", {
            "LeftAnchorOffset": 353,
            "TopAnchorOffset": 2,
            "RightAnchorOffset": 4,
            "BottomAnchorOffset": 2,
            "LeftAnchorToLeft": True,
            "TopAnchorToTop": True,
            "BottomAnchorToTop": False,
        })
        text = _set_item_fields(text, "DragBox", "PIWDragBox1", {
            "TopAnchorOffset": 0,
            "BottomAnchorOffset": 24,
            "RightAnchorOffset": 356,
            "TopAnchorToTop": True,
            "BottomAnchorToTop": True,
            "RightAnchorToLeft": True,
        })
    else:
        raise ValueError(f"unexpected Pet variant: {filename}")

    # Start effects at the visible edge. Side rails flow down first; horizontal
    # trays flow across first so every variant has an intentional reading order.
    text = _set_item_fields(text, "TileLayoutBox", "PIW_BuffButtons", {
        # The top-tray variant grows upward; anchoring its icons to the lower
        # seam avoids recreating an empty band above Companion after resize.
        "AnchorToTop": filename != "EQUI_PetInfoWindow2.xml",
        "HorizontalFirst": filename != "EQUI_PetInfoWindow3.xml",
    })
    return text


def restyle(path: Path) -> bool:
    payload = path.read_bytes()
    text = payload.decode("utf-8")
    revised = text
    for index in range(14):
        revised = _set_button(revised, index)
    revised = _direct_command_pieces(revised)
    revised = _remove_flow_grid(revised)
    revised = _polish_buff_host(revised)
    revised = _style_buff_chip(revised, path.name)
    revised = _clean_subwindow_chrome(revised)
    revised = _frame_outer_window(revised)
    revised = _compact_status_rows(revised)
    revised = _compact_geometry(revised, path.name)
    ET.fromstring(revised)
    if revised == text:
        return False
    path.write_bytes(revised.encode("utf-8"))
    return True


def main() -> int:
    changed = [path.name for path in VARIANTS if restyle(path)]
    print("pet layouts updated: " + (", ".join(changed) if changed else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
