#!/usr/bin/env python3
"""Apply the canonical Legends Combat Command Center treatment.

The files in this pass are hand-authored SIDL, so this transformer deliberately
edits only named blocks and leaves ordering, comments, ScreenIDs, EQTypes, and
all latent legacy rows untouched.  Running it repeatedly is idempotent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable


REPO = Path(__file__).resolve().parent.parent
SKIN = REPO / "spinui_reloaded"

# "Vellum & Ember" accessibility palette: parchment ink, aged brass, and a
# spirit-blue arcane accent.  The same values live in spinui_theme.py for
# rendered documentation; they are repeated here so this script has no
# Pillow/runtime dependency.
TEXT = (241, 231, 212)
TEXT_DIM = (172, 154, 126)
GOLD = (208, 162, 84)
GOLD_BRIGHT = (248, 214, 140)
CYAN = (126, 170, 244)
CYAN_BRIGHT = (178, 206, 252)
HP = (222, 62, 72)
MANA = (66, 126, 244)
ENDURANCE = (208, 162, 84)
PET = (152, 132, 104)

# --- Spell Effects / Song Effects row geometry ----------------------------
# EverQuest draws two things on a buff button that the skin cannot separate:
# the remaining-duration countdown, centered on the button, and a solid
# beneficial/detrimental background plate that is stretched to fill it.  One
# button width controls both, so a chip wide enough to give the countdown its
# own column also stretches that plate into a slab of flat blue beside every
# icon.  The plate wins: an icon-sized chip keeps it as a frame around the art
# it belongs to, and the countdown rides on the icon in ember gold with a
# shadow, which is legible and is how EverQuest has always shown it.
#
#   row x=1     x=25    x=36                        x=206
#       [ icon 20 ][gap][ effect name 170          ][pad]
#          ^ countdown centered at x=13
#
# EFFECT_TIMER_HALF_WIDTH is the widest countdown the row must swallow; the
# audit proves it still cannot reach the name column.
EFFECT_ROW_WIDTH = 216
EFFECT_CHIP = (24, 20)
EFFECT_ICON = (20, 20)
EFFECT_TIMER_FONT = 3
EFFECT_TIMER_HALF_WIDTH = 16
# The chip must never extend meaningfully past its icon, or the client's
# background plate becomes a slab instead of a frame.
EFFECT_PLATE_BLEED = 4
EFFECT_NAME_X = 36
EFFECT_NAME_TAIL = 10
EFFECT_NAME_WIDTH = EFFECT_ROW_WIDTH - EFFECT_NAME_X - EFFECT_NAME_TAIL

# The authored 360x193 command frames remain unchanged on first load. Their
# anchored subwindows can safely contract to these Legends-compatible bounds,
# so users may resize them without clipping the command rows.
PLAYER_MIN_SIZE = (280, 174)
TARGET_MIN_SIZE = (260, 174)
ATTACK_EDGE_WIDTH = 4
ATTACK_FRAME_SIZE = (128, 32)
ATTACK_PULSE_FRAME_COUNT = 8
ATTACK_FRAME_ORIGINS = tuple(
    index * ATTACK_FRAME_SIZE[1] for index in range(ATTACK_PULSE_FRAME_COUNT)
)
ATTACK_TEXTURE_SIZE = (
    ATTACK_FRAME_SIZE[0], ATTACK_FRAME_SIZE[1] * ATTACK_PULSE_FRAME_COUNT)
ATTACK_PULSE_MS = 70
ATTACK_HIGH_EDGE_WIDTH = 5
ATTACK_HIGH_TEXTURE = "AttackIndicator.tga"
PLAYER_HIGH_VISIBILITY_VARIANT = "EQUI_PlayerWindow1.xml"
PLAYER_HIGH_VISIBILITY_MENU_NAME = "High-Visibility Attack Frame"
PLAYER_HIGH_VISIBILITY_SIZE = (360, 174)
PLAYER_HIGH_VISIBILITY_SUBWINDOW_TOP = 51

# Older SpinUI releases exposed a large collection of visual variants.  Most of
# those files predate the July Legends schema and can lose live controls when a
# saved layout still selects them.  Keep the filenames as compatibility aliases
# (so existing INIs continue to load), but make every alias use the canonical,
# current-schema command frame. PlayerWindow1 is the deliberate high-visibility
# auto-attack option; CastSpellWnd3 is the named-and-numbered spell ledger. The
# canonical player frame and icon-only spell deck remain the untouched defaults.
SPELL_LEDGER_VARIANT = "EQUI_CastSpellWnd3.xml"
SPELL_LEDGER_MENU_NAME = "SpinUI Spell Ledger"
SPELL_LEDGER_EQTYPES = (
    60, 61, 62, 63, 64, 65, 66, 67, 133, 138, 149, 150, 414, 415,
)
SPELL_LEDGER_ROW_SIZE = (155, 30)
SPELL_LEDGER_ICON_SIZE = (26, 26)
SPELL_LEDGER_WINDOW_SIZE = (157, 477)
SPELL_LEDGER_WINDOW_BOUNDS = (157, 96, 640, 477)

# Extended targets remain a familiar single column at the current default
# width, but each complete 34px target row is now a tile.  Horizontal-first
# flow makes widening the window useful: a second, third, or later column is
# added only when a whole row fits, while the existing vertical scrollbar
# remains the safe fallback at narrow sizes.
EXTENDED_TARGET_COUNT = 23
EXTENDED_TARGET_ROW_SIZE = (146, 34)
EXTENDED_TARGET_WINDOW_SIZE = (178, 300)
EXTENDED_TARGET_MIN_SIZE = (170, 58)
EXTENDED_TARGET_GUTTER = 4
EXTENDED_TARGET_LAYOUT = "ETW_ResponsiveLayout"
EXTENDED_TARGET_TILE = "ETW_Targets"
EXTENDED_TARGET_BLOCK_BEGIN = "SPIN-XTAR-RESPONSIVE:BEGIN"
EXTENDED_TARGET_BLOCK_END = "SPIN-XTAR-RESPONSIVE:END"

CANONICAL_VARIANTS = {
    "EQUI_PlayerWindow.xml": tuple(f"EQUI_PlayerWindow{i}.xml" for i in range(2, 7)),
    "EQUI_TargetWindow.xml": tuple(f"EQUI_TargetWindow{i}.xml" for i in range(1, 7)),
    "EQUI_TargetOfTargetWindow.xml": ("EQUI_TargetOfTargetWindow1.xml",),
    "EQUI_BuffWindow.xml": tuple(f"EQUI_BuffWindow{i}.xml" for i in range(1, 18)),
    "EQUI_ShortDurationBuffWindow.xml": tuple(
        f"EQUI_ShortDurationBuffWindow{i}.xml" for i in range(1, 18)
    ),
    "EQUI_CastingWindow.xml": ("EQUI_CastingWindow1.xml",),
    "EQUI_CastSpellWnd.xml": tuple(f"EQUI_CastSpellWnd{i}.xml" for i in range(1, 3)),
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def write_ascii(path: Path, text: str) -> None:
    """Write deterministic LF XML without inherited trailing whitespace."""
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        original_prefix = re.match(r"[ \t]*", line).group(0)
        prefix = original_prefix
        while " \t" in prefix:
            prefix = prefix.replace(" \t", "\t")
        lines.append(prefix + line[len(original_prefix):])
    cleaned = "\n".join(lines) + "\n"
    path.write_text(cleaned, encoding="ascii", newline="")


def item_pattern(tag: str, name: str) -> re.Pattern[str]:
    return re.compile(
        rf"<{tag}\s+item=\"{re.escape(name)}\">.*?</{tag}>", re.DOTALL
    )


def change_item(text: str, tag: str, name: str,
                transform: Callable[[str], str]) -> str:
    pattern = item_pattern(tag, name)
    match = pattern.search(text)
    if match is None:
        fail(f"missing {tag} item {name}")
    updated = transform(match.group(0))
    return text[:match.start()] + updated + text[match.end():]


def change_matching(text: str, tag: str, name_pattern: str,
                    transform: Callable[[str], str]) -> str:
    pattern = re.compile(
        rf"<{tag}\s+item=\"(?:{name_pattern})\">.*?</{tag}>", re.DOTALL
    )
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return transform(match.group(0))

    result = pattern.sub(repl, text)
    if count == 0:
        fail(f"no {tag} items matched {name_pattern}")
    return result


def set_value(block: str, tag: str, value: str | int,
              *, required: bool = True) -> str:
    pattern = re.compile(rf"(<{tag}>).*?(</{tag}>)", re.DOTALL)
    result, count = pattern.subn(
        lambda m: f"{m.group(1)}{value}{m.group(2)}", block, count=1
    )
    if required and count != 1:
        fail(f"missing <{tag}> in item block")
    return result


def set_or_add_value(block: str, tag: str, value: str | int,
                     *, after: str) -> str:
    """Set a scalar tag, or add it after a stable neighboring scalar tag."""
    if re.search(rf"<{tag}>.*?</{tag}>", block, re.DOTALL):
        return set_value(block, tag, value)
    anchor = re.search(rf"</{after}>", block)
    if anchor is None:
        fail(f"cannot add <{tag}>: missing </{after}> anchor")
    indent_match = re.search(rf"\n([ \t]+)<{after}>", block)
    indent = indent_match.group(1) if indent_match else "\t\t"
    addition = f"\n{indent}<{tag}>{value}</{tag}>"
    return block[:anchor.end()] + addition + block[anchor.end():]


def set_container(block: str, container: str, **values: int) -> str:
    pattern = re.compile(
        rf"(<{container}>)(.*?)(</{container}>)", re.DOTALL
    )
    match = pattern.search(block)
    if match is None:
        fail(f"missing <{container}> in item block")
    body = match.group(2)
    for tag, value in values.items():
        body = set_value(body, tag, value)
    replacement = match.group(1) + body + match.group(3)
    return block[:match.start()] + replacement + block[match.end():]


def set_color(block: str, container: str, rgb: tuple[int, int, int],
              *, insert: bool = False) -> str:
    pattern = re.compile(
        rf"(<{container}>)(.*?)(</{container}>)", re.DOTALL
    )
    match = pattern.search(block)
    if match is None:
        if not insert:
            fail(f"missing <{container}> in item block")
        indent_match = re.search(r"\n([ \t]+)<", block)
        indent = indent_match.group(1) if indent_match else "\t\t"
        child = indent + "\t"
        payload = (
            f"{indent}<{container}>\n"
            f"{child}<R>{rgb[0]}</R>\n"
            f"{child}<G>{rgb[1]}</G>\n"
            f"{child}<B>{rgb[2]}</B>\n"
            f"{indent}</{container}>\n"
        )
        anchor = re.search(r"\n[ \t]+<(?:RelativePosition|Text|NoWrap)>", block)
        if anchor is None:
            fail(f"no insertion point for <{container}>")
        return block[:anchor.start() + 1] + payload + block[anchor.start() + 1:]
    body = match.group(2)
    for tag, value in zip(("R", "G", "B"), rgb):
        body = set_value(body, tag, value)
    replacement = match.group(1) + body + match.group(3)
    return block[:match.start()] + replacement + block[match.end():]


def set_font(block: str, value: int) -> str:
    if re.search(r"<Font>.*?</Font>", block, re.DOTALL):
        return set_value(block, "Font", value)
    match = re.search(r"</(?:ScreenID|EQType)>", block)
    if match is None:
        fail("cannot add font: item has no ScreenID or EQType")
    indent_match = re.search(r"\n([ \t]+)<(?:ScreenID|EQType)>", block)
    indent = indent_match.group(1) if indent_match else "\t\t"
    return block[:match.end()] + f"\n{indent}<Font>{value}</Font>" + block[match.end():]


def style_gauge(block: str, color: tuple[int, int, int],
                lines: tuple[int, int, int] | None = None) -> str:
    block = set_color(block, "FillTint", color)
    if lines is not None:
        block = set_color(block, "LinesFillTint", lines)
    return block


def show_total_progression_ticks(block: str) -> str:
    """Draw fixed gauge ticks without EQ's misleading 20% sub-progress."""
    block = set_value(block, "DrawLinesFill", "false")
    return set_or_add_value(
        block, "Lines", "A_GaugeLines", after="Fill"
    )


def set_root_widths(block: str, width: int) -> str:
    # Group Size and GroupSizeN records are all direct children of the root.
    return re.sub(r"(<CX>)\d+(</CX>)", rf"\g<1>{width}\g<2>", block)


def style_buff_file(path: Path, prefix: str, count: int,
                    title: str, height: int) -> None:
    text = path.read_text(encoding="ascii")
    template = f"{prefix}_Player_Buff_Template"
    # Icon-sized chip: the countdown rides on the icon (Font 3, ember gold,
    # shadowed) and the client's background plate stays a frame rather than a
    # stretched slab.  See the EFFECT_* block above for why these are one lever.
    text = change_item(
        text, "Button", template,
        lambda b: set_color(
            set_container(
                set_container(
                    set_or_add_value(
                        set_font(b, EFFECT_TIMER_FONT), "FontShadow", "true",
                        after="Font"),
                    "Size", CX=EFFECT_CHIP[0], CY=EFFECT_CHIP[1]),
                "DecalSize", CX=EFFECT_ICON[0], CY=EFFECT_ICON[1],
            ),
            "TextColor", GOLD_BRIGHT, insert=True,
        ),
    )
    text = change_item(
        text, "Button", template,
        lambda b: set_container(b, "DecalOffset", X=0, Y=0),
    )
    # One icon per row, paired with its name: the box must flow
    # vertically. Horizontal-first flow put the first three buffs side by
    # side in row one while their names stacked, scrambling every row.
    text = change_item(
        text, "TileLayoutBox", f"{prefix}_Buttons",
        lambda b: set_value(
            set_value(b, "HorizontalFirst", "false"),
            "RightAnchorOffset", EFFECT_ROW_WIDTH - EFFECT_CHIP[0] - 1),
    )
    for index in range(count):
        label = f"{prefix}_Buff{index}"

        def label_style(block: str) -> str:
            block = set_font(block, 3)
            block = set_container(block, "Location", X=EFFECT_NAME_X, Y=1)
            block = set_container(block, "Size",
                                  CX=EFFECT_NAME_WIDTH, CY=18)
            return set_color(block, "TextColor", TEXT, insert=True)

        text = change_item(text, "Label", label, label_style)

    text = change_item(
        text, "Label", f"{prefix}_Buff_FrontSpacer",
        lambda b: set_container(
            set_container(b, "Location", X=0, Y=1),
            "Size", CX=EFFECT_NAME_X, CY=18
        ),
    )
    text = change_item(
        text, "Label", f"{prefix}_Buff_BackSpacer",
        lambda b: set_container(
            set_container(b, "Location",
                          X=EFFECT_ROW_WIDTH - EFFECT_NAME_TAIL, Y=1),
            "Size", CX=EFFECT_NAME_TAIL, CY=18
        ),
    )
    text = change_item(
        text, "Screen", f"{prefix}_00_Screen",
        lambda b: set_container(b, "Size", CX=EFFECT_ROW_WIDTH, CY=20),
    )
    text = change_item(
        text, "TileLayoutBox", f"{prefix}_Buttons",
        lambda b: set_value(set_value(b, "LeftAnchorOffset", 1), "Spacing", 0),
    )
    text = change_item(
        text, "TileLayoutBox", f"{prefix}_Labels",
        lambda b: set_value(set_value(b, "LeftAnchorOffset", 1), "Spacing", 0),
    )
    window_name = "BuffWindow" if prefix == "BW" else "ShortDurationBuffWindow"
    background_name = f"{prefix}_Background"

    def background_style(block: str) -> str:
        # Active effect buttons remain fully interactive, while the unused
        # maximum-slot canvas no longer paints an opaque inset rectangle.
        block = set_or_add_value(
            block, "Style_Transparent", "true", after="Style_HScroll"
        )
        return set_value(block, "Style_Border", "false")

    text = change_item(text, "Screen", background_name, background_style)

    def window_style(block: str) -> str:
        block = set_value(block, "Text", title)
        block = set_container(block, "Size", CX=EFFECT_ROW_WIDTH, CY=height)
        block = set_value(block, "Style_Transparent", "true")
        block = set_value(block, "DrawTemplate", "WDT_RoundedTransparentNoArrow")
        block = set_value(block, "Style_Titlebar", "true")
        # Keep the title rail for dragging, but never draw a perimeter around
        # the entire maximum buff-slot canvas.  That outline is visible even
        # when most effect rows are empty and recreates the oversized slab the
        # transparent treatment is intended to remove.
        block = set_value(block, "Style_Border", "false")
        block = set_value(block, "Style_ClientMovable", "true")
        block = set_or_add_value(
            block, "ClickThroughEmptyBuffs", "true",
            after="Style_ClientMovable",
        )
        block = set_value(block, "KeepOnScreen", "true")
        return block

    text = change_item(text, "Screen", window_name, window_style)
    write_ascii(path, text)


def style_player() -> None:
    path = SKIN / "EQUI_PlayerWindow.xml"
    text = path.read_text(encoding="ascii")
    # XP is ember gold and AA is venom. Both progression bars use a fixed tick
    # overlay while hiding the legacy sub-progress fill so their lengths match
    # the client's total percentage labels.
    gauges = {
        "Player_HP": (HP, None),
        "Player_Mana": (MANA, None),
        "Player_Fatigue": (ENDURANCE, None),
        "Pet_HP": (PET, None),
        "PW_ExpGauge": (GOLD, None),
        "PW_AltAdvGauge": (CYAN, None),
        "PW_Castspell_Gauge": (CYAN, None),
    }
    for name, (color, lines) in gauges.items():
        text = change_item(text, "Gauge", name,
                           lambda b, c=color, l=lines: style_gauge(b, c, l))
    # LinesFill represents progress inside the current 20% bubble, so 17% XP
    # appears 85% full and 10% AA appears 50% full when it is enabled. The
    # static Lines layer retains clear increments without changing fill length.
    for name in ("PW_ExpGauge", "PW_AltAdvGauge"):
        text = change_item(
            text, "Gauge", name,
            show_total_progression_ticks,
        )
    for name, color in (("PW_Level", GOLD_BRIGHT), ("PW_Class", TEXT),
                        ("PW_StanceLabel", GOLD_BRIGHT),
                        ("PW_InvocationInfo", CYAN)):
        text = change_item(
            text, "Label", name,
            lambda b, c=color: set_color(set_font(b, 4), "TextColor", c,
                                         insert=True),
        )

    def stance_rail(block: str) -> str:
        # Legends can return a longer stance name (for example "Defensive
        # Stance") than the stock two-point font was designed around.  Give
        # the left rail a real, inset column and enough line height for Font 4
        # descenders without letting it collide with invocation text.
        block = set_value(block, "TopAnchorOffset", 96)
        block = set_value(block, "BottomAnchorOffset", 112)
        block = set_value(block, "LeftAnchorOffset", 6)
        block = set_value(block, "RightAnchorOffset", 132)
        return block

    def invocation_rail(block: str) -> str:
        # Reserve an independent right-aligned column for values such as
        # "Empower".  The four-pixel gutter keeps both dynamic labels legible
        # even when the three-class identity uses the full command-frame width.
        # Sits below the AA percent readout band (83..93) with a clear gap.
        block = set_value(block, "TopAnchorOffset", 96)
        block = set_value(block, "BottomAnchorOffset", 112)
        block = set_value(block, "LeftAnchorOffset", 232)
        block = set_value(block, "RightAnchorOffset", 6)
        return block

    text = change_item(text, "Label", "PW_StanceLabel", stance_rail)
    text = change_item(text, "Label", "PW_InvocationInfo", invocation_rail)

    text = change_item(
        text, "TextureInfo", "AttackIndicator.tga",
        lambda b: set_container(
            b, "Size", CX=ATTACK_TEXTURE_SIZE[0], CY=ATTACK_TEXTURE_SIZE[1]),
    )

    attack_animations = {
        "A_AttackIndicator": ATTACK_FRAME_SIZE,
        "A_AttackIndicatorTop": (ATTACK_FRAME_SIZE[0], ATTACK_EDGE_WIDTH),
        "A_AttackIndicatorBottom": (ATTACK_FRAME_SIZE[0], ATTACK_EDGE_WIDTH),
        "A_AttackIndicatorLeft": (ATTACK_EDGE_WIDTH, ATTACK_FRAME_SIZE[1]),
        "A_AttackIndicatorRight": (ATTACK_EDGE_WIDTH, ATTACK_FRAME_SIZE[1]),
        "A_AttackIndicatorFill": ATTACK_FRAME_SIZE,
    }

    def attack_animation(block: str, size: tuple[int, int]) -> str:
        block = set_value(block, "Cycle", "true")
        block = re.sub(r"\n\t\t<Frames>.*?</Frames>", "", block,
                       flags=re.DOTALL)

        def frame(origin_y: int) -> str:
            return (
                "\n\t\t<Frames>\n"
                "\t\t\t<Texture>AttackIndicator.tga</Texture>\n"
                "\t\t\t<Location>\n"
                "\t\t\t\t<X>0</X>\n"
                f"\t\t\t\t<Y>{origin_y}</Y>\n"
                "\t\t\t</Location>\n"
                "\t\t\t<Size>\n"
                f"\t\t\t\t<CX>{size[0]}</CX>\n"
                f"\t\t\t\t<CY>{size[1]}</CY>\n"
                "\t\t\t</Size>\n"
                f"\t\t\t<Duration>{ATTACK_PULSE_MS}</Duration>\n"
                "\t\t</Frames>"
            )

        cycle_marker = "</Cycle>"
        cycle_end = block.find(cycle_marker)
        if cycle_end < 0:
            fail("attack animation has no Cycle element")
        cycle_end += len(cycle_marker)
        frames = "".join(frame(origin) for origin in ATTACK_FRAME_ORIGINS)
        return block[:cycle_end] + frames + block[cycle_end:]

    for name, size in attack_animations.items():
        text = change_item(
            text, "Ui2DAnimation", name,
            lambda b, s=size: attack_animation(b, s),
        )

    attack_edges = {
        "A_AttackIndicatorAnimTop": (70, 70 + ATTACK_EDGE_WIDTH, 0, 0),
        "A_AttackIndicatorAnimBottom": (2 + ATTACK_EDGE_WIDTH, 2, 0, 0),
        "A_AttackIndicatorAnimLeft": (70, 2, 0, ATTACK_EDGE_WIDTH),
        "A_AttackIndicatorAnimRight": (70, 2, ATTACK_EDGE_WIDTH, 0),
    }
    for name, offsets in attack_edges.items():
        def attack_edge(block: str, values=offsets) -> str:
            for tag, value in zip((
                    "TopAnchorOffset", "BottomAnchorOffset",
                    "LeftAnchorOffset", "RightAnchorOffset"), values):
                block = set_value(block, tag, value)
            block = set_value(block, "AutoDraw", "false")
            block = set_value(block, "AutoStretch", "true")
            return block
        text = change_item(text, "StaticAnimation", name, attack_edge)

    def attack_fill(block: str) -> str:
        for tag, value in (
                ("Animation", "A_AttackIndicatorFill"),
                ("RelativePosition", "true"),
                ("AutoDraw", "false"),
                ("AutoStretch", "true"),
                ("LeftAnchorOffset", 0),
                ("TopAnchorOffset", 70),
                ("RightAnchorOffset", 0),
                ("BottomAnchorOffset", 2),
                ("TopAnchorToTop", "true"),
                ("BottomAnchorToTop", "false"),
                ("LeftAnchorToLeft", "true"),
                ("RightAnchorToLeft", "false"),
                ("Style_Transparent", "true")):
            block = set_value(block, tag, value)
        return block

    text = change_item(
        text, "StaticAnimation", "A_AttackIndicatorAnimFill", attack_fill,
    )

    def root_style(block: str) -> str:
        block = set_container(block, "Size", CX=360, CY=193)
        block = set_or_add_value(
            block, "MinHSize", PLAYER_MIN_SIZE[0], after="Size"
        )
        block = set_or_add_value(
            block, "MinVSize", PLAYER_MIN_SIZE[1], after="MinHSize"
        )
        block = set_value(block, "MenuName", "Legends Command Frame - Buffs on Top")
        # The root exists mostly to host the interaction/buff canvas.  Painting
        # its full 360x193 border creates the large faint perimeter seen in the
        # live client; the compact PlayerSubWindow remains the visible frame.
        block = set_value(block, "Style_Border", "false")
        block = set_value(block, "Style_Sizable", "true")
        return block

    text = change_item(text, "Screen", "PlayerWindow", root_style)
    write_ascii(path, text)


def style_target() -> None:
    path = SKIN / "EQUI_TargetWindow.xml"
    text = path.read_text(encoding="ascii")
    gauges = {
        "Target_HP": HP,
        "Target_HP_NameOnly": HP,
        "TTargetOfTarget_HP": HP,
        "Target_Mana": MANA,
        "Target_Endurance": ENDURANCE,
        "Castspell_Gauge": CYAN,
    }
    for name, color in gauges.items():
        text = change_item(text, "Gauge", name,
                           lambda b, c=color: style_gauge(b, c))
    for name, color in (("Target_Class", TEXT), ("Target_Level", GOLD_BRIGHT),
                        ("ToT_Class", TEXT), ("ToT_Level", GOLD_BRIGHT)):
        text = change_item(
            text, "Label", name,
            lambda b, c=color: set_color(set_font(b, 3), "TextColor", c,
                                         insert=True),
        )

    def root_style(block: str) -> str:
        block = set_container(block, "Size", CX=360, CY=193)
        block = set_or_add_value(
            block, "MinHSize", TARGET_MIN_SIZE[0], after="Size"
        )
        block = set_or_add_value(
            block, "MinVSize", TARGET_MIN_SIZE[1], after="MinHSize"
        )
        block = set_value(block, "MenuName", "Legends Command Frame - Buffs on Top")
        # Keep the root transparent and interactive while letting the compact
        # TargetSubWindow provide the only visible perimeter.
        block = set_value(block, "Style_Border", "false")
        block = set_value(block, "Style_Sizable", "true")
        return block

    text = change_item(text, "Screen", "TargetWindow", root_style)
    write_ascii(path, text)


def style_target_of_target() -> None:
    path = SKIN / "EQUI_TargetOfTargetWindow.xml"
    text = path.read_text(encoding="ascii")
    text = change_item(text, "Gauge", "TargetOfTarget_HP",
                       lambda b: style_gauge(b, HP))
    for name, color in (("ToTW_Level", GOLD_BRIGHT), ("ToTW_Class", TEXT)):
        text = change_item(
            text, "Label", name,
            lambda b, c=color: set_color(set_font(b, 3), "TextColor", c),
        )

    def root_style(block: str) -> str:
        block = set_container(block, "Size", CX=240, CY=53)
        block = set_value(block, "Text", "TARGET OF TARGET")
        block = set_value(block, "MinVSize", 53)
        block = set_value(block, "MaxVSize", 53)
        block = set_value(block, "MinHSize", 180)
        block = set_value(block, "MaxHSize", 360)
        return block

    text = change_item(text, "Screen", "TargetOfTargetWindow", root_style)
    write_ascii(path, text)


def style_group() -> None:
    path = SKIN / "EQUI_GroupWindow.xml"
    text = path.read_text(encoding="ascii")
    for pattern, color in ((r"GW_Gauge(?:[1-9]|10|11)", HP),
                           (r"GW_ManaGauge(?:[1-9]|10|11)", MANA),
                           (r"GW_STAGauge(?:[1-9]|10|11)", ENDURANCE),
                           (r"GW_PetGauge(?:[1-9]|10|11)", PET)):
        text = change_matching(text, "Gauge", pattern,
                               lambda b, c=color: style_gauge(b, c))
    text = change_matching(text, "Label", r"GW_HPLabel(?:[1-9]|10|11)",
                           lambda b: set_font(b, 3))
    text = change_matching(text, "Label", r"GW_AggroPctPlayer(?:[1-9]|10|11)",
                           lambda b: set_color(set_font(b, 2), "TextColor",
                                               GOLD_BRIGHT, insert=True))

    def root_style(block: str) -> str:
        block = set_root_widths(block, 230)
        block = set_container(block, "Size", CX=230, CY=70)
        for index in range(1, 12):
            expected_height = 120 + (index - 1) * 42
            block = set_container(block, f"GroupSize{index}",
                                  CX=230, CY=expected_height)
        block = set_value(block, "Text", "GROUP")
        block = set_value(block, "MenuName", "Legends Command Frames")
        return block

    text = change_item(text, "Screen", "GroupWindow", root_style)
    write_ascii(path, text)


def style_extended_targets() -> None:
    path = SKIN / "EQUI_ExtendedTargetWnd.xml"
    text = path.read_text(encoding="ascii")
    target_index = r"(?:[0-9]|1[0-9]|2[0-2])"
    for pattern, color in ((rf"ETW_Gauge{target_index}", HP),
                           (rf"ETW_ManaGauge{target_index}", MANA),
                           (rf"ETW_CastGauge{target_index}", CYAN),
                           (rf"ETW_STAGauge{target_index}", ENDURANCE)):
        text = change_matching(text, "Gauge", pattern,
                               lambda b, c=color: style_gauge(b, c))
    text = change_matching(text, "Label", rf"ETW_HPLabel{target_index}",
                           lambda b: set_font(b, 2))
    text = change_matching(
        text, "Label", rf"ETW_AggroPct{target_index}",
        lambda b: set_color(set_font(b, 2), "TextColor", GOLD_BRIGHT,
                            insert=True),
    )

    # The stock file anchors every slot directly to the root with cumulative
    # Y offsets.  A row wrapper needs the exact same geometry expressed in its
    # own local 34px coordinate system.  Assign canonical offsets rather than
    # subtracting in-place so repeated generator runs remain idempotent.
    local_offsets = (
        ("Label", "ETW_AggroPct", 20, 32),
        ("Gauge", "ETW_Gauge", 1, 23),
        ("Gauge", "ETW_ManaGauge", 24, 28),
        ("Gauge", "ETW_CastGauge", 24, 28),
        ("Gauge", "ETW_STAGauge", 29, 31),
        ("Label", "ETW_HPLabel", 14, 30),
        ("Label", "ETW_HPPercLabel", 14, 30),
        ("Button", "ETW_Role", 3, 19),
    )
    for index in range(EXTENDED_TARGET_COUNT):
        for tag, stem, top, bottom in local_offsets:
            def localize(block: str, top_offset: int = top,
                         bottom_offset: int = bottom) -> str:
                block = set_value(block, "TopAnchorOffset", top_offset)
                return set_value(block, "BottomAnchorOffset", bottom_offset)

            text = change_item(text, tag, f"{stem}{index}", localize)

    # Replace our prior generated block before rebuilding it.  The canonical
    # target controls stay hand-authored and untouched outside the local Y
    # normalization above; only wrappers and layout mechanics are generated.
    marked = re.compile(
        rf"(?:\r?\n[ \t]*)+"
        rf"<!-- {re.escape(EXTENDED_TARGET_BLOCK_BEGIN)} -->.*?"
        rf"<!-- {re.escape(EXTENDED_TARGET_BLOCK_END)} -->[ \t]*"
        rf"(?:\r?\n[ \t]*)*",
        re.DOTALL,
    )
    text, marked_count = marked.subn("\n\n\t", text)
    if marked_count > 1:
        fail("duplicate generated responsive XTAR blocks")

    rows = []
    for index in range(EXTENDED_TARGET_COUNT):
        row_pieces = "\n".join(
            f"\t\t<Pieces>{stem}{index}</Pieces>"
            for stem in (
                "ETW_AggroPct", "ETW_Gauge", "ETW_ManaGauge",
                "ETW_CastGauge", "ETW_STAGauge", "ETW_HPLabel",
                "ETW_HPPercLabel", "ETW_Role",
            )
        )
        rows.append(f'''\t<Screen item="ETW_Ext{index}">
\t\t<ScreenID>ETW_Ext{index}</ScreenID>
\t\t<RelativePosition>true</RelativePosition>
\t\t<Size>
\t\t\t<CX>{EXTENDED_TARGET_ROW_SIZE[0]}</CX>
\t\t\t<CY>{EXTENDED_TARGET_ROW_SIZE[1]}</CY>
\t\t</Size>
\t\t<Style_Transparent>true</Style_Transparent>
\t\t<Style_TransparentControl>true</Style_TransparentControl>
\t\t<Style_Border>false</Style_Border>
\t\t<Style_Sizable>false</Style_Sizable>
{row_pieces}
\t</Screen>''')

    tile_pieces = "\n".join(
        f"\t\t<Pieces>Screen:ETW_Ext{index}</Pieces>"
        for index in range(EXTENDED_TARGET_COUNT)
    )
    responsive_block = f'''\t<!-- {EXTENDED_TARGET_BLOCK_BEGIN} -->
\t<LayoutVertical item="{EXTENDED_TARGET_LAYOUT}">
\t\t<Padding>0</Padding>
\t\t<ResizeVertical>true</ResizeVertical>
\t\t<ResizeHorizontal>true</ResizeHorizontal>
\t</LayoutVertical>

{chr(10).join(rows)}

\t<TileLayoutBox item="{EXTENDED_TARGET_TILE}">
\t\t<ScreenID>{EXTENDED_TARGET_TILE}</ScreenID>
\t\t<RelativePosition>true</RelativePosition>
\t\t<AutoStretch>true</AutoStretch>
\t\t<TopAnchorOffset>1</TopAnchorOffset>
\t\t<BottomAnchorOffset>1</BottomAnchorOffset>
\t\t<LeftAnchorOffset>1</LeftAnchorOffset>
\t\t<RightAnchorOffset>1</RightAnchorOffset>
\t\t<TopAnchorToTop>true</TopAnchorToTop>
\t\t<BottomAnchorToTop>false</BottomAnchorToTop>
\t\t<LeftAnchorToLeft>true</LeftAnchorToLeft>
\t\t<RightAnchorToLeft>false</RightAnchorToLeft>
\t\t<Style_Transparent>true</Style_Transparent>
\t\t<Style_TransparentControl>true</Style_TransparentControl>
\t\t<Spacing>0</Spacing>
\t\t<SecondarySpacing>{EXTENDED_TARGET_GUTTER}</SecondarySpacing>
\t\t<HorizontalFirst>true</HorizontalFirst>
\t\t<AnchorToTop>true</AnchorToTop>
\t\t<AnchorToLeft>true</AnchorToLeft>
\t\t<FirstPieceTemplate>true</FirstPieceTemplate>
{tile_pieces}
\t</TileLayoutBox>
\t<!-- {EXTENDED_TARGET_BLOCK_END} -->'''

    root_match = item_pattern("Screen", "ExtendedTargetWnd").search(text)
    if root_match is None:
        fail("missing Screen item ExtendedTargetWnd")
    root_line_start = text.rfind("\n", 0, root_match.start()) + 1
    text = (
        text[:root_line_start] + responsive_block + "\n\n"
        + text[root_line_start:]
    )

    def root_style(block: str) -> str:
        block = set_container(
            block, "Size",
            CX=EXTENDED_TARGET_WINDOW_SIZE[0],
            CY=EXTENDED_TARGET_WINDOW_SIZE[1],
        )
        # EQ only instantiates the responsive tile through the parent layout;
        # moving scroll ownership onto TileLayoutBox leaves a framed but empty
        # XTAR window in-game.  Keep the proven parent layout and root scroll,
        # but omit TileLayoutBox/SnapToChildren so the content cannot force the
        # outer window back to the full 23-row height after the user shrinks it.
        block = set_or_add_value(
            block, "Layout", EXTENDED_TARGET_LAYOUT,
            after="RelativePosition",
        )
        block = set_value(block, "Text", "EXTENDED TARGETS")
        block = set_value(block, "MinHSize", EXTENDED_TARGET_MIN_SIZE[0])
        block = set_value(block, "MinVSize", EXTENDED_TARGET_MIN_SIZE[1])
        block = set_value(block, "Style_VScroll", "true")
        block = set_value(block, "Style_AutoVScroll", "true")
        # Replace the legacy 184-control flat list as one operation.  This also
        # corrects its slot-20 typo (CastGauge21 appeared twice while
        # CastGauge20 was omitted) and makes every target move as a complete
        # responsive row.
        block, piece_count = re.subn(
            r"\n[ \t]*<Pieces>.*?</Pieces>", "", block,
        )
        if piece_count == 0:
            fail("ExtendedTargetWnd has no child pieces to replace")
        closing = block.rfind("\n\t</Screen>")
        if closing < 0:
            fail("malformed ExtendedTargetWnd closing tag")
        piece = f"\n\t\t<Pieces>TileLayoutBox:{EXTENDED_TARGET_TILE}</Pieces>"
        return block[:closing] + piece + block[closing:]

    text = change_item(text, "Screen", "ExtendedTargetWnd", root_style)
    write_ascii(path, text)


CAST_DRAG_BLOCK = """\t<!-- Preserve the client's full-surface drag contract for this titleless window. -->
\t<DragBox item="CWDragBox">
\t\t<ScreenID>CWDragBox</ScreenID>
\t\t<AutoStretch>true</AutoStretch>
\t\t<TopAnchorToTop>true</TopAnchorToTop>
\t\t<LeftAnchorToLeft>true</LeftAnchorToLeft>
\t\t<RightAnchorToLeft>false</RightAnchorToLeft>
\t\t<BottomAnchorToTop>false</BottomAnchorToTop>
\t\t<TopAnchorOffset>0</TopAnchorOffset>
\t\t<LeftAnchorOffset>0</LeftAnchorOffset>
\t\t<RightAnchorOffset>0</RightAnchorOffset>
\t\t<BottomAnchorOffset>0</BottomAnchorOffset>
\t\t<Style_Transparent>true</Style_Transparent>
\t</DragBox>
"""


def style_casting() -> None:
    path = SKIN / "EQUI_CastingWindow.xml"
    text = path.read_text(encoding="ascii")
    if 'item="CWDragBox"' not in text:
        anchor = '\t<Screen item="CastingWindow">'
        if anchor not in text:
            fail("missing CastingWindow insertion point")
        text = text.replace(anchor, CAST_DRAG_BLOCK + "\n" + anchor, 1)

    def gauge_style(block: str) -> str:
        block = style_gauge(block, CYAN)
        block = set_value(block, "TopAnchorOffset", 6)
        return set_value(block, "BottomAnchorOffset", 30)

    text = change_item(text, "Gauge", "Casting_Gauge", gauge_style)

    def label_style(block: str) -> str:
        block = set_font(block, 4)
        block = set_color(block, "TextColor", TEXT, insert=True)
        block = set_value(block, "TopAnchorOffset", 6)
        return set_value(block, "BottomAnchorOffset", 30)

    text = change_item(text, "Label", "Casting_SpellName", label_style)

    def root_style(block: str) -> str:
        block = set_container(block, "Size", CX=380, CY=36)
        block = set_value(block, "Text", "CASTING")
        block = set_or_add_value(block, "MenuName", "Legends Command Cast Bar",
                                 after="Text")
        block = set_value(block, "DrawTemplate", "WDT_RoundedNoTitle")
        block = set_value(block, "Style_Titlebar", "false")
        block = set_value(block, "MinHSize", 200)
        block = set_value(block, "MinVSize", 36)
        block = set_value(block, "MaxHSize", 600)
        block = set_value(block, "MaxVSize", 36)
        if "<Pieces>DragBox:CWDragBox</Pieces>" not in block:
            block = block.replace(
                "\n\t</Screen>",
                "\n\t\t<Pieces>DragBox:CWDragBox</Pieces>\n\t</Screen>",
                1,
            )
        return block

    text = change_item(text, "Screen", "CastingWindow", root_style)
    write_ascii(path, text)


def style_spell_gems() -> None:
    path = SKIN / "EQUI_CastSpellWnd.xml"
    text = path.read_text(encoding="ascii")
    for index in range(14):
        def gem_style(block: str) -> str:
            # Legends' own default_modern skin uses a 36px icon centered in
            # this exact 40px socket.  The former 24px/13px geometry left the
            # art undersized and visibly off-center in horizontal layouts.
            block = set_value(block, "SpellIconOffsetX", 2)
            block = set_value(block, "SpellIconOffsetY", 2)
            block = set_value(block, "SpellIconSizeX", 36)
            return set_value(block, "SpellIconSizeY", 36)

        text = change_item(text, "SpellGem", f"CSPW_Spell{index}", gem_style)
    text = change_item(
        text, "Screen", "CastSpellWnd",
        lambda b: set_or_add_value(
            set_container(b, "Size", CX=52, CY=623),
            "MenuName", "Legends Spell Deck", after="Text",
        ),
    )
    write_ascii(path, text)


SPELL_LEDGER_ASSET_BEGIN = "SPIN-SPELL-LEDGER-ASSETS:BEGIN"
SPELL_LEDGER_ASSET_END = "SPIN-SPELL-LEDGER-ASSETS:END"
SPELL_LEDGER_ASSETS = rf'''
	<!-- {SPELL_LEDGER_ASSET_BEGIN} -->
	<!-- Vellum & Ember row plate states.  These live in the central animation
	     registry because dynamically selected display-type XML cannot publish
	     new Ui2DAnimation symbols reliably in the EverQuest client. -->
	<TextureInfo item="spin_spell_ledger.tga">
		<Size>
			<CX>256</CX>
			<CY>96</CY>
		</Size>
	</TextureInfo>
	<Ui2DAnimation item="A_SpinSpellLedgerBackground">
		<Cycle>false</Cycle>
		<Frames>
			<Texture>spin_spell_ledger.tga</Texture>
			<Location>
				<X>0</X>
				<Y>0</Y>
			</Location>
			<Size>
				<CX>155</CX>
				<CY>30</CY>
			</Size>
		</Frames>
	</Ui2DAnimation>
	<Ui2DAnimation item="A_SpinSpellLedgerHolder">
		<Cycle>false</Cycle>
		<Frames>
			<Texture>spin_spell_ledger.tga</Texture>
			<Location>
				<X>0</X>
				<Y>32</Y>
			</Location>
			<Size>
				<CX>155</CX>
				<CY>30</CY>
			</Size>
		</Frames>
	</Ui2DAnimation>
	<Ui2DAnimation item="A_SpinSpellLedgerHighlight">
		<Cycle>false</Cycle>
		<Frames>
			<Texture>spin_spell_ledger.tga</Texture>
			<Location>
				<X>0</X>
				<Y>64</Y>
			</Location>
			<Size>
				<CX>155</CX>
				<CY>30</CY>
			</Size>
		</Frames>
	</Ui2DAnimation>
	<!-- {SPELL_LEDGER_ASSET_END} -->'''


def register_spell_ledger_assets() -> None:
    """Publish the ledger draw symbols where EverQuest builds its registry."""
    path = SKIN / "EQUI_Animations.xml"
    text = path.read_text(encoding="ascii")
    marked = re.compile(
        rf"(?:\r?\n[ \t]*)+"
        rf"<!-- {re.escape(SPELL_LEDGER_ASSET_BEGIN)} -->.*?"
        rf"<!-- {re.escape(SPELL_LEDGER_ASSET_END)} -->[ \t]*"
        rf"(?:\r?\n[ \t]*)*",
        re.DOTALL,
    )
    text, count = marked.subn("", text)
    if count > 1:
        fail("duplicate central Spell Ledger animation blocks")
    text, schema_count = re.subn(
        r"(<Schema\b[^>]*/>)",
        lambda match: (
            match.group(1) + "\n\n" + SPELL_LEDGER_ASSETS + "\n\n"
        ),
        text,
        count=1,
    )
    if schema_count != 1:
        fail("missing Schema declaration in EQUI_Animations.xml")
    write_ascii(path, text)


def spell_ledger_row(index: int) -> str:
    """Return the dynamic name, static slot number, and responsive row."""
    eq_type = SPELL_LEDGER_EQTYPES[index]
    slot = index + 1
    return f'''
	<Label item="CSPW_Spell_{index}_Label">
		<ScreenID>CSPW_Spell_{index}_Label</ScreenID>
		<Font>2</Font>
		<RelativePosition>true</RelativePosition>
		<Location>
			<X>33</X>
			<Y>0</Y>
		</Location>
		<Size>
			<CX>104</CX>
			<CY>30</CY>
		</Size>
		<EQType>{eq_type}</EQType>
		<TextColor>
			<R>{TEXT[0]}</R>
			<G>{TEXT[1]}</G>
			<B>{TEXT[2]}</B>
		</TextColor>
		<FontShadow>true</FontShadow>
		<NoWrap>true</NoWrap>
		<AlignLeft>true</AlignLeft>
		<AlignVCenter>true</AlignVCenter>
		<Style_Tooltip>false</Style_Tooltip>
	</Label>
	<Label item="CSPW_Spell_{index}_Number">
		<ScreenID>CSPW_Spell_{index}_Number</ScreenID>
		<Font>2</Font>
		<RelativePosition>true</RelativePosition>
		<Location>
			<X>139</X>
			<Y>0</Y>
		</Location>
		<Size>
			<CX>12</CX>
			<CY>30</CY>
		</Size>
		<Text>{slot}</Text>
		<TextColor>
			<R>{GOLD_BRIGHT[0]}</R>
			<G>{GOLD_BRIGHT[1]}</G>
			<B>{GOLD_BRIGHT[2]}</B>
		</TextColor>
		<FontShadow>true</FontShadow>
		<NoWrap>true</NoWrap>
		<AlignRight>true</AlignRight>
		<AlignVCenter>true</AlignVCenter>
		<Style_Tooltip>false</Style_Tooltip>
	</Label>
	<LayoutBox item="CSPW_Spell_{index}">
		<ScreenID>CSPW_Spell_{index}</ScreenID>
		<RelativePosition>true</RelativePosition>
		<AutoStretch>false</AutoStretch>
		<Size>
			<CX>{SPELL_LEDGER_ROW_SIZE[0]}</CX>
			<CY>{SPELL_LEDGER_ROW_SIZE[1]}</CY>
		</Size>
		<Style_Transparent>true</Style_Transparent>
		<Style_Tooltip>true</Style_Tooltip>
		<Style_Titlebar>false</Style_Titlebar>
		<Style_Closebox>false</Style_Closebox>
		<Style_Minimizebox>false</Style_Minimizebox>
		<Style_Border>false</Style_Border>
		<Style_Sizable>false</Style_Sizable>
		<AnchorToTop>true</AnchorToTop>
		<AnchorToLeft>true</AnchorToLeft>
		<Pieces>SpellGem:CSPW_Spell{index}</Pieces>
		<Pieces>CSPW_Spell_{index}_Label</Pieces>
		<Pieces>CSPW_Spell_{index}_Number</Pieces>
	</LayoutBox>'''


def style_spell_ledger_variant() -> None:
    """Build Alternate3 as a resizable icon + name + slot spell ledger.

    The canonical file is always the source so every live Legends binding and
    any future schema addition survives.  Only row presentation is changed.
    """
    source_path = SKIN / "EQUI_CastSpellWnd.xml"
    text = source_path.read_text(encoding="ascii")

    for index in range(14):
        def gem_style(block: str, row_index: int = index) -> str:
            block = set_container(
                block, "Size",
                CX=SPELL_LEDGER_ROW_SIZE[0], CY=SPELL_LEDGER_ROW_SIZE[1],
            )
            block = set_value(block, "Holder", "A_SpinSpellLedgerHolder")
            block = set_value(
                block, "Background", "A_SpinSpellLedgerBackground"
            )
            block = set_value(
                block, "Highlight", "A_SpinSpellLedgerHighlight"
            )
            block = set_value(block, "SpellIconOffsetX", 2)
            block = set_value(block, "SpellIconOffsetY", 2)
            block = set_value(
                block, "SpellIconSizeX", SPELL_LEDGER_ICON_SIZE[0]
            )
            block = set_value(
                block, "SpellIconSizeY", SPELL_LEDGER_ICON_SIZE[1]
            )
            return block + spell_ledger_row(row_index)

        text = change_item(text, "SpellGem", f"CSPW_Spell{index}", gem_style)

    def layout_style(block: str) -> str:
        block = set_value(block, "Spacing", 2)
        block = set_value(block, "SecondarySpacing", 2)
        block = set_value(block, "HorizontalFirst", "true")
        block = set_value(block, "SnapToChildren", "true")
        for index in range(14):
            old = f"<Pieces>SpellGem:CSPW_Spell{index}</Pieces>"
            new = f"<Pieces>LayoutBox:CSPW_Spell_{index}</Pieces>"
            if old not in block:
                fail(f"missing spell ledger layout member {index}")
            block = block.replace(old, new, 1)
        return block

    text = change_item(
        text, "TileLayoutBox", "CSPW_SpellGemLayout", layout_style
    )

    def root_style(block: str) -> str:
        block = set_container(
            block, "Size",
            CX=SPELL_LEDGER_WINDOW_SIZE[0], CY=SPELL_LEDGER_WINDOW_SIZE[1],
        )
        block = set_value(block, "Text", "SPELL LEDGER // ICON + NAME + SLOT")
        block = set_or_add_value(
            block, "MenuName", SPELL_LEDGER_MENU_NAME, after="Text"
        )
        block = set_value(
            block, "TooltipReference",
            "Resizable SpinUI spell list with icons, names, and slot numbers",
        )
        block = set_value(block, "DrawTemplate", "WDT_RoundedNoTitle")
        block = set_value(block, "Style_Titlebar", "false")
        block = set_value(block, "Style_Closebox", "false")
        block = set_value(block, "Style_Border", "true")
        block = set_value(block, "Style_Sizable", "true")
        block = set_value(block, "Style_ClientMovable", "true")
        min_h, min_v, max_h, max_v = SPELL_LEDGER_WINDOW_BOUNDS
        block = set_or_add_value(block, "MinHSize", min_h, after="Style_Sizable")
        block = set_or_add_value(block, "MinVSize", min_v, after="MinHSize")
        block = set_or_add_value(block, "MaxHSize", max_h, after="MinVSize")
        return set_or_add_value(block, "MaxVSize", max_v, after="MaxHSize")

    text = change_item(text, "Screen", "CastSpellWnd", root_style)
    write_ascii(SKIN / SPELL_LEDGER_VARIANT, text)


def style_hotbuttons() -> None:
    path = SKIN / "EQUI_HotButtonWnd.xml"
    text = path.read_text(encoding="ascii")
    text = change_matching(text, "HotButton", r"HB_Button(?:[1-9]|10|11|12)",
                           lambda b: set_font(b, 2))
    for name in ("HB_HorizontalCurrentPageLabel", "HB_VerticalCurrentPageLabel"):
        text = change_item(
            text, "Label", name,
            lambda b: set_color(set_font(b, 2), "TextColor", GOLD_BRIGHT,
                                insert=True),
        )
    write_ascii(path, text)


CYAN_DIM = (88, 122, 186)

# Twin-wing rail: static STANCE / INVOCATION captions bracket the bar, the
# dynamic names sit inside their wing, and an ember gem marks the split.
WING_BLOCK = """	<!-- SPIN-WING: stance / invocation twin-wing rail -->
	<TextureInfo item="spin_deco.tga">
		<Size>
			<CX>128</CX>
			<CY>128</CY>
		</Size>
	</TextureInfo>
	<Ui2DAnimation item="A_SpinWingGem">
		<Cycle>true</Cycle>
		<Frames>
			<Texture>spin_deco.tga</Texture>
			<Location>
				<X>112</X>
				<Y>64</Y>
			</Location>
			<Size>
				<CX>12</CX>
				<CY>12</CY>
			</Size>
			<Hotspot>
				<X>0</X>
				<Y>0</Y>
			</Hotspot>
			<Duration>1000</Duration>
		</Frames>
	</Ui2DAnimation>
	<Label item="SW_StanceCaption">
		<Font>1</Font>
		<RelativePosition>true</RelativePosition>
		<AutoStretch>true</AutoStretch>
		<TopAnchorOffset>2</TopAnchorOffset>
		<BottomAnchorOffset>13</BottomAnchorOffset>
		<LeftAnchorOffset>2</LeftAnchorOffset>
		<RightAnchorOffset>46</RightAnchorOffset>
		<TopAnchorToTop>true</TopAnchorToTop>
		<BottomAnchorToTop>true</BottomAnchorToTop>
		<LeftAnchorToLeft>true</LeftAnchorToLeft>
		<RightAnchorToLeft>true</RightAnchorToLeft>
		<Text>STANCE</Text>
		<TextColor>
			<R>208</R>
			<G>162</G>
			<B>84</B>
		</TextColor>
		<NoWrap>true</NoWrap>
		<AlignCenter>false</AlignCenter>
		<AlignRight>false</AlignRight>
		<AlignLeft>true</AlignLeft>
	</Label>
	<Label item="SW_InvocationCaption">
		<Font>1</Font>
		<RelativePosition>true</RelativePosition>
		<AutoStretch>true</AutoStretch>
		<TopAnchorOffset>2</TopAnchorOffset>
		<BottomAnchorOffset>13</BottomAnchorOffset>
		<LeftAnchorOffset>62</LeftAnchorOffset>
		<RightAnchorOffset>2</RightAnchorOffset>
		<TopAnchorToTop>true</TopAnchorToTop>
		<BottomAnchorToTop>true</BottomAnchorToTop>
		<LeftAnchorToLeft>false</LeftAnchorToLeft>
		<RightAnchorToLeft>false</RightAnchorToLeft>
		<Text>INVOCATION</Text>
		<TextColor>
			<R>88</R>
			<G>122</G>
			<B>186</B>
		</TextColor>
		<NoWrap>true</NoWrap>
		<AlignCenter>false</AlignCenter>
		<AlignRight>true</AlignRight>
		<AlignLeft>false</AlignLeft>
	</Label>
	<StaticAnimation item="SW_WingGem">
		<ScreenID>SW_WingGem</ScreenID>
		<RelativePosition>true</RelativePosition>
		<Location>
			<X>214</X>
			<Y>1</Y>
		</Location>
		<Size>
			<CX>12</CX>
			<CY>12</CY>
		</Size>
		<Animation>A_SpinWingGem</Animation>
	</StaticAnimation>
"""

WING_PIECES = """		<Pieces>SW_StanceCaption</Pieces>
		<Pieces>SW_InvocationCaption</Pieces>
		<Pieces>SW_WingGem</Pieces>
"""


def style_stance_file(path: Path, menu_name: str | None = None) -> None:
    text = path.read_text(encoding="ascii")
    if 'item="SW_StanceCaption"' not in text:
        schema = re.search(r"<Schema[^>]*/>", text)
        if schema is None:
            fail(f"missing Schema in {path.name}")
        text = text[:schema.end()] + "\n" + WING_BLOCK + text[schema.end():]
        rail_anchor = "\t\t<Pieces>SW_StanceLabel</Pieces>\n"
        if rail_anchor not in text:
            fail(f"missing stance rail pieces in {path.name}")
        text = text.replace(rail_anchor, WING_PIECES + rail_anchor, 1)
    # The static captions ship inside WING_BLOCK, so re-assert their palette on
    # every run — a theme change must reach files that already carry the block.
    text = change_item(text, "Label", "SW_StanceCaption",
                       lambda b: set_color(b, "TextColor", GOLD))
    text = change_item(text, "Label", "SW_InvocationCaption",
                       lambda b: set_color(b, "TextColor", CYAN_DIM))
    def center_in_wing(block: str, color, left: int, right: int) -> str:
        # The dynamic names center inside their wing box, so any stance or
        # invocation name the client returns sits balanced with no overlap —
        # the boxes stop short of the center gem on both sides.
        block = set_color(set_font(block, 3), "TextColor", color)
        block = set_value(block, "LeftAnchorOffset", left)
        block = set_value(block, "RightAnchorOffset", right)
        block = set_value(block, "AlignCenter", "true")
        block = set_value(block, "AlignLeft", "false")
        block = set_value(block, "AlignRight", "false")
        return block

    text = change_item(
        text, "Label", "SW_StanceLabel",
        lambda b: center_in_wing(b, GOLD_BRIGHT, 48, 208),
    )
    text = change_item(
        text, "Label", "SW_InvocationLabel",
        lambda b: center_in_wing(b, CYAN, 208, 64),
    )
    text = change_item(text, "Button", "SW_ButtonTemplate",
                       lambda b: set_font(b, 2))

    # Legends' July stance-layout fix removed the trailing right inset from
    # every orientation and the trailing bottom inset from top-rail variants.
    # Retain that live client contract so /loadskin can reuse the saved frame.
    for orientation in (
            "SW_HorizontalOrientationTemplate",
            "SW_VerticalOrientationTemplate"):
        def orientation_style(block: str) -> str:
            block = set_value(block, "RightAnchorOffset", 0)
            if path.name != "EQUI_StanceWnd2.xml":
                block = set_value(block, "BottomAnchorOffset", 0)
            return block

        text = change_item(text, "Screen", orientation, orientation_style)

    def root_style(block: str) -> str:
        block = set_container(block, "Size", CX=440, CY=56)
        if menu_name is not None:
            block = set_value(block, "MenuName", menu_name)
        block = set_value(block, "MinHSize", 20)
        block = set_value(block, "MinVSize", 20)
        return block

    text = change_item(text, "Screen", "StanceWnd", root_style)
    write_ascii(path, text)


def style_stance() -> None:
    style_stance_file(
        SKIN / "EQUI_StanceWnd.xml", "Stance and Invocation Command Bar"
    )
    # These two remain useful positional alternatives.  Unlike the retired
    # legacy frame variants, both already contain the complete July binding set.
    style_stance_file(SKIN / "EQUI_StanceWnd1.xml")
    style_stance_file(SKIN / "EQUI_StanceWnd2.xml")


def sync_canonical_variants() -> None:
    """Turn schema-stale variants into hidden, safe compatibility aliases."""
    marker = (
        "\n\n\t<!-- Canonical Legends compatibility alias: current bindings, "
        "signature visuals. -->"
    )
    for canonical_name, variant_names in CANONICAL_VARIANTS.items():
        source = (SKIN / canonical_name).read_text(encoding="ascii")
        source = re.sub(
            r"\n[ \t]*<MenuName>.*?</MenuName>", "", source,
            flags=re.DOTALL,
        )
        source, count = re.subn(
            r"(<Schema\b[^>]*/>)", rf"\g<1>{marker}", source, count=1
        )
        if count != 1:
            fail(f"missing Schema declaration in {canonical_name}")
        for variant_name in variant_names:
            write_ascii(SKIN / variant_name, source)


def style_high_visibility_player_variant() -> None:
    """Expose Alternate 1 as a binding-safe, unmistakable attack frame."""
    source = (SKIN / "EQUI_PlayerWindow.xml").read_text(encoding="ascii")
    source, count = re.subn(
        r"(<Schema\b[^>]*/>)",
        (r"\g<1>\n\n\t<!-- Alternate 1: native auto-attack state with a "
         r"pure-red high-visibility treatment. -->"),
        source,
        count=1,
    )
    if count != 1:
        fail("missing Schema declaration in high-visibility player variant")

    def animation_size(block: str, size: tuple[int, int]) -> str:
        pattern = re.compile(
            r"(<Size>\s*<CX>)\d+(</CX>\s*<CY>)\d+(</CY>\s*</Size>)"
        )
        return pattern.sub(
            lambda match: (
                match.group(1) + str(size[0]) + match.group(2)
                + str(size[1]) + match.group(3)
            ),
            block,
        )

    for name, size in (
            ("A_AttackIndicatorTop", (ATTACK_FRAME_SIZE[0], ATTACK_HIGH_EDGE_WIDTH)),
            ("A_AttackIndicatorBottom", (ATTACK_FRAME_SIZE[0], ATTACK_HIGH_EDGE_WIDTH)),
            ("A_AttackIndicatorLeft", (ATTACK_HIGH_EDGE_WIDTH, ATTACK_FRAME_SIZE[1])),
            ("A_AttackIndicatorRight", (ATTACK_HIGH_EDGE_WIDTH, ATTACK_FRAME_SIZE[1]))):
        source = change_item(
            source, "Ui2DAnimation", name,
            lambda block, wanted=size: animation_size(block, wanted),
        )

    geometry = {
        "A_AttackIndicatorAnimTop": (
            PLAYER_HIGH_VISIBILITY_SUBWINDOW_TOP,
            PLAYER_HIGH_VISIBILITY_SUBWINDOW_TOP + ATTACK_HIGH_EDGE_WIDTH,
            0, 0),
        "A_AttackIndicatorAnimBottom": (
            2 + ATTACK_HIGH_EDGE_WIDTH, 2, 0, 0),
        "A_AttackIndicatorAnimLeft": (
            PLAYER_HIGH_VISIBILITY_SUBWINDOW_TOP,
            2, 0, ATTACK_HIGH_EDGE_WIDTH),
        "A_AttackIndicatorAnimRight": (
            PLAYER_HIGH_VISIBILITY_SUBWINDOW_TOP,
            2, ATTACK_HIGH_EDGE_WIDTH, 0),
    }
    for name, offsets in geometry.items():
        def high_edge(block: str, values=offsets) -> str:
            for tag, value in zip((
                    "TopAnchorOffset", "BottomAnchorOffset",
                    "LeftAnchorOffset", "RightAnchorOffset"), values):
                block = set_value(block, tag, value)
            return block
        source = change_item(source, "StaticAnimation", name, high_edge)

    source = change_item(
        source, "StaticAnimation", "A_AttackIndicatorAnimFill",
        lambda block: set_value(
            block, "TopAnchorOffset", PLAYER_HIGH_VISIBILITY_SUBWINDOW_TOP),
    )
    source = change_item(
        source, "Screen", "PlayerSubWindow",
        lambda block: set_value(
            block, "TopAnchorOffset", PLAYER_HIGH_VISIBILITY_SUBWINDOW_TOP),
    )
    source = change_item(
        source, "Screen", "PW_BuffWindow",
        lambda block: set_value(
            block, "BottomAnchorOffset",
            PLAYER_HIGH_VISIBILITY_SUBWINDOW_TOP + 2),
    )
    for name, top, bottom in (
            ("PW_DragBox", 53, 73),
            ("PW_DragBox2", 91, 181),
            ("PWDragBox3", 53, 73)):
        def compact_drag(block: str, wanted_top=top,
                         wanted_bottom=bottom) -> str:
            block = set_value(block, "TopAnchorOffset", wanted_top)
            return set_value(block, "BottomAnchorOffset", wanted_bottom)
        source = change_item(source, "DragBox", name, compact_drag)

    def compact_root(block: str) -> str:
        block = set_value(
            block, "MenuName", PLAYER_HIGH_VISIBILITY_MENU_NAME)
        block = set_container(
            block, "Size", CX=PLAYER_HIGH_VISIBILITY_SIZE[0],
            CY=PLAYER_HIGH_VISIBILITY_SIZE[1])
        block = set_value(block, "MinVSize", PLAYER_HIGH_VISIBILITY_SIZE[1])
        return set_or_add_value(
            block, "MaxVSize", PLAYER_HIGH_VISIBILITY_SIZE[1],
            after="MinVSize")

    source = change_item(
        source, "Screen", "PlayerWindow", compact_root,
    )
    write_ascii(SKIN / PLAYER_HIGH_VISIBILITY_VARIANT, source)


def style_experience_gauges() -> None:
    """One color identity per progression bar, everywhere it appears.

    XP is ember gold and AA is venom. Inventory gauges show total 0-100
    progression without EQ's legacy 20-percent LinesFill sub-tick overlay.
    """
    inventory_names = (
        "EQUI_InventoryWindow.xml",
        "EQUI_InventoryWindow1.xml",
        "EQUI_InventoryWindow2.xml",
        "EQUI_InventoryWindow3.xml",
    )
    for inventory_name in inventory_names:
        path = SKIN / inventory_name
        text = path.read_text(encoding="utf-8")
        text = change_item(
            text, "Gauge", "IW_ExpGauge",
            lambda b: show_total_progression_ticks(style_gauge(b, GOLD)),
        )
        text = change_item(
            text, "Gauge", "IW_AltAdvGauge",
            lambda b: show_total_progression_ticks(style_gauge(b, CYAN)),
        )
        path.write_text(text, encoding="utf-8")

    path = SKIN / "EQUI_AAWindow.xml"
    text = path.read_text(encoding="ascii")
    text = change_item(text, "Gauge", "AAW_ExpGauge",
                       lambda b: style_gauge(b, CYAN, CYAN_BRIGHT))
    write_ascii(path, text)


def style_raid() -> None:
    path = SKIN / "EQUI_RaidWindow.xml"
    text = path.read_text(encoding="ascii")
    text = change_matching(
        text, "Page", r"RAID_(?:Member|Note)Page",
        lambda b: set_color(b, "TabTextActiveColor", GOLD_BRIGHT),
    )
    text = change_item(text, "Screen", "RaidWindow",
                       lambda b: set_value(b, "Text", "RAID // EIGHT"))
    write_ascii(path, text)


def main() -> int:
    style_buff_file(SKIN / "EQUI_BuffWindow.xml", "BW", 30,
                    "SPELL EFFECTS", 640)
    style_buff_file(SKIN / "EQUI_ShortDurationBuffWindow.xml", "SDBW", 15,
                    "SONG EFFECTS", 324)
    style_player()
    style_target()
    style_target_of_target()
    style_group()
    style_extended_targets()
    style_casting()
    style_spell_gems()
    style_hotbuttons()
    style_stance()
    style_experience_gauges()
    style_raid()
    sync_canonical_variants()
    style_high_visibility_player_variant()
    register_spell_ledger_assets()
    style_spell_ledger_variant()
    print("Combat Command Center restyle: complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
