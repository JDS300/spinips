"""Canonical SpinUI "Vellum & Ember" visual tokens.

The identity is an adventurer's field journal bound for Norrath: dark oiled
leather panels, aged-brass frames and corner caps, warm parchment text, a
glowing ember seam across every titlebar, and a cool spirit-blue reserved for
the arcane (AA, casting, selection glow).  Renderers and atlas generators
import this file so documentation matches the textures shipped to the client.
"""

from __future__ import annotations

import re

BG0 = (12, 9, 6)          # deepest umber / exterior shadow
BG1 = (19, 14, 9)         # oiled-leather panel
BG2 = (30, 22, 14)        # raised control
BG3 = (46, 34, 21)        # hover / selected surface
VOID = (9, 7, 4)

LINE_SOFT = (52, 40, 25)
LINE = (104, 80, 48)      # brass-brown frame
LINE_BRIGHT = (166, 130, 82)  # polished brass corner caps

GOLD_DEEP = (112, 82, 34)
GOLD = (208, 162, 84)     # aged brass
GOLD_BRIGHT = (248, 214, 140)
EMBER = (242, 118, 44)    # forge seam / interaction heat
EMBER_DEEP = (140, 56, 18)
EMBER_BRIGHT = (255, 176, 100)

CYAN_DEEP = (48, 74, 132)
CYAN = (126, 170, 244)    # spirit-blue arcane accent

TEXT = (241, 231, 212)    # warm parchment ink
TEXT_DIM = (172, 154, 126)
PARCHMENT = (222, 204, 162)

HP = (222, 62, 72)
MANA = (66, 126, 244)
ENDUR = (208, 162, 84)
PET = (152, 132, 104)
GREEN = (66, 207, 139)
RED = HP


ACCENT_KEYS = (
    "CYAN_DEEP", "CYAN", "GOLD_DEEP", "GOLD", "GOLD_BRIGHT", "EMBER",
)


def _rgb(value: tuple[int, int, int]) -> tuple[int, int, int]:
    if len(value) != 3 or any(not isinstance(channel, int) or not 0 <= channel <= 255
                              for channel in value):
        raise ValueError(f"invalid RGB color: {value!r}")
    return value


def rgb_from_hex(value: str) -> tuple[int, int, int]:
    """Parse one CSS-style ``#RRGGBB`` color for theme/project files."""
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(f"invalid color {value!r}; expected #RRGGBB")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def hex_from_rgb(value: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in _rgb(value))


def _mix(first: tuple[int, int, int], second: tuple[int, int, int],
         amount: float) -> tuple[int, int, int]:
    return tuple(round(first[index] * (1 - amount) + second[index] * amount)
                 for index in range(3))


DEFAULT_ACCENTS = {
    "CYAN_DEEP": CYAN_DEEP,
    "CYAN": CYAN,
    "GOLD_DEEP": GOLD_DEEP,
    "GOLD": GOLD,
    "GOLD_BRIGHT": GOLD_BRIGHT,
    "EMBER": EMBER,
}


def accent_palette(*, venom: tuple[int, int, int] = CYAN,
                   gold: tuple[int, int, int] = GOLD,
                   ember: tuple[int, int, int] = EMBER) -> dict[str, tuple[int, int, int]]:
    """Create the complete accent ramp used by XML, atlases, and previews.

    The canonical colors return their hand-tuned deep/bright companions.
    Custom choices derive accessible companions deterministically so a theme
    project can be rebuilt without storing generated binary data.
    """
    venom, gold, ember = _rgb(venom), _rgb(gold), _rgb(ember)
    return {
        "CYAN_DEEP": (
            CYAN_DEEP if venom == CYAN
            else _mix(venom, (0, 0, 0), 0.52)
        ),
        "CYAN": venom,
        "GOLD_DEEP": (
            GOLD_DEEP if gold == GOLD
            else _mix(gold, (0, 0, 0), 0.48)
        ),
        "GOLD": gold,
        "GOLD_BRIGHT": (
            GOLD_BRIGHT if gold == GOLD
            else _mix(gold, (255, 244, 205), 0.42)
        ),
        "EMBER": ember,
    }


def palette_from_hex(values: dict[str, str]) -> dict[str, tuple[int, int, int]]:
    """Expand the three user-facing colors from a theme JSON document."""
    required = {"venom", "gold", "ember"}
    missing = required - values.keys()
    if missing:
        raise ValueError(f"theme is missing: {', '.join(sorted(missing))}")
    return accent_palette(
        venom=rgb_from_hex(values["venom"]),
        gold=rgb_from_hex(values["gold"]),
        ember=rgb_from_hex(values["ember"]),
    )
