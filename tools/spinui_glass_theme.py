"""Canonical tokens for the optional SpinUI Glass skin.

Glass is an EQ-native interpretation of a modern MMO interface: midnight
translucent panes, one-pixel ice edges, toxic-mint interaction light, violet
selection energy, and frosted typography.  Resource colors remain semantic;
the palette below owns chrome and text rather than HP/mana/endurance meaning.
"""

from __future__ import annotations


NAME = "SpinUI Glass"
SLUG = "spinui_glass"

ICE = (105, 225, 242)
ICE_BRIGHT = (207, 247, 255)
MINT = (85, 242, 190)
MINT_BRIGHT = (164, 255, 224)
VIOLET = (171, 128, 255)
FROST = (232, 248, 252)
FROST_DIM = (139, 180, 190)


def texture_tokens() -> dict[str, tuple[int, ...]]:
    """Return the complete surface palette consumed by the atlas generator."""
    return {
        "BG0": (3, 8, 14),
        "BG1": (6, 15, 24),
        "BG2": (10, 27, 40),
        "BG3": (18, 48, 66),
        "VOID": (2, 6, 11),
        "LINE_SOFT": (22, 54, 70),
        "LINE": (48, 121, 143),
        "LINE_BRIGHT": (153, 239, 250),
        "GOLD_DEEP": (42, 78, 124),
        "GOLD": (114, 156, 255),
        "GOLD_BRIGHT": ICE_BRIGHT,
        "EMBER": MINT,
        "EMBER_DEEP": (21, 124, 98),
        "EMBER_BRIGHT": MINT_BRIGHT,
        "CYAN_DEEP": (63, 39, 112),
        "CYAN": VIOLET,
        "TEXT": FROST,
        "TEXT_DIM": FROST_DIM,
        "FRAME_OUTER": (1, 5, 9),
        "FRAME_VOID": (2, 8, 13),
        "CONTROL_OUTER": (2, 8, 13),
        "GAUGE_OUTER": (0, 3, 6),
        "SLOT_SHADOW": (0, 2, 5),
        "BEVEL_LIGHT": (198, 248, 255),
        "CONTROL_NORMAL_BOTTOM": (4, 12, 20),
        "CONTROL_FLYBY_TOP": (12, 56, 69),
        "CONTROL_FLYBY_BOTTOM": (5, 22, 32),
        "CONTROL_PRESSED_TOP": (37, 34, 73),
        "CONTROL_PRESSED_BOTTOM": (9, 14, 28),
        "CONTROL_ACTIVE_TOP": (20, 79, 78),
        "CONTROL_ACTIVE_BOTTOM": (6, 28, 36),
        "CONTROL_DISABLED_TOP": (7, 14, 20),
        "CONTROL_DISABLED_BOTTOM": (3, 8, 13),
        "TITLE_TOP": (12, 38, 50),
        "TITLE_BOTTOM": (4, 12, 20),
        "INNER_FRAME": (12, 32, 45),
        "TILE_LIGHT": (7, 20, 29, 224),
        "TILE_DARK": (4, 13, 21, 230),
        "TILE_INNER": (6, 17, 25, 236),
        "TILE_VOID": (2, 8, 14, 238),
    }


# Only presentation colors are remapped in XML.  Gauge FillTint and other
# semantic data colors are deliberately excluded by the builder.
XML_TEXT_COLOR_MAP = {
    (241, 231, 212): FROST,
    (172, 154, 126): FROST_DIM,
    (248, 214, 140): ICE_BRIGHT,
    (208, 162, 84): ICE,
    (242, 118, 44): MINT,
    (126, 170, 244): VIOLET,
    (112, 82, 34): (42, 78, 124),
    (48, 74, 132): (63, 39, 112),
}

VISUAL_COLOR_TAGS = {
    "TextColor", "DisabledColor", "HighlightColor", "SelectedColor",
}
