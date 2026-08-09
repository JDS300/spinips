#!/usr/bin/env python3
"""Paint SpinUI's native auto-attack indicators.

EverQuest owns the visibility of the four ``A_AttackIndicatorAnim*`` pieces
in ``EQUI_PlayerWindow.xml``.  They are hidden while auto-attack is off and
shown while it is on, so the texture is a reliable client-state indicator and
does not need log parsing or combat heuristics.

The texture contains two stacked 128x32 states. EverQuest cycles between a
white-hot scarlet rail and a deep crimson rail, giving the complete command
frame a deliberate pulse that remains obvious over both Reloaded's brown
chrome and Glass's midnight chrome. The remaining texture provides a pulsing
translucent wash without obscuring health, mana, endurance, experience, or AA
information.

``AttackIndicatorHigh.tga`` is the opt-in Alternate 1 treatment. It retains
the same native visibility hook but uses a solid, nine-pixel pure-red perimeter
and a stronger red wash. This is intentionally unmistakable for players who
prefer certainty over subtlety; the canonical default remains unchanged.

Run from the repository root:
    python tools/paint_attack_indicator.py
"""

from pathlib import Path

from PIL import Image

from generate_spinui_textures import save_tga


REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "spinui_reloaded" / "AttackIndicator.tga"
HIGH_OUTPUT = REPO / "spinui_reloaded" / "AttackIndicatorHigh.tga"
FRAME_SIZE = (128, 32)
SIZE = (128, 64)
EDGE_WIDTH = 5
HIGH_EDGE_WIDTH = 9

ATTACK_EDGE = (255, 250, 244, 255)
ATTACK_INNER = (255, 96, 82, 255)
ATTACK_HALO = (255, 8, 34, 255)
ATTACK_SOFT = (236, 0, 26, 255)
ATTACK_FADE = (196, 0, 22, 242)
ATTACK_BED = (148, 0, 18, 108)
ATTACK_RAIL = (
    ATTACK_EDGE,
    ATTACK_INNER,
    ATTACK_HALO,
    ATTACK_SOFT,
    ATTACK_FADE,
)
PULSE_EDGE = (255, 56, 52, 255)
PULSE_INNER = (226, 0, 24, 255)
PULSE_HALO = (178, 0, 20, 255)
PULSE_SOFT = (126, 0, 16, 242)
PULSE_FADE = (82, 0, 12, 218)
PULSE_BED = (88, 0, 12, 70)
PULSE_RAIL = (
    PULSE_EDGE,
    PULSE_INNER,
    PULSE_HALO,
    PULSE_SOFT,
    PULSE_FADE,
)

HIGH_ATTACK_RED = (255, 0, 0, 255)
HIGH_ATTACK_RAIL = (
    HIGH_ATTACK_RED,
    HIGH_ATTACK_RED,
    HIGH_ATTACK_RED,
    HIGH_ATTACK_RED,
    HIGH_ATTACK_RED,
    (255, 0, 0, 245),
    (255, 0, 0, 225),
    (255, 0, 0, 200),
    (255, 0, 0, 170),
)
HIGH_PULSE_RAIL = (
    HIGH_ATTACK_RED,
    HIGH_ATTACK_RED,
    (255, 28, 28, 255),
    HIGH_ATTACK_RED,
    (255, 0, 0, 245),
    (255, 0, 0, 225),
    (255, 0, 0, 200),
    (255, 0, 0, 175),
    (255, 0, 0, 145),
)
HIGH_ATTACK_BED = (255, 0, 0, 112)
HIGH_PULSE_BED = (255, 0, 0, 54)


def render() -> Image.Image:
    image = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    pixels = image.load()
    width, frame_height = FRAME_SIZE
    for frame, (rail, bed) in enumerate((
            (ATTACK_RAIL, ATTACK_BED),
            (PULSE_RAIL, PULSE_BED))):
        origin_y = frame * frame_height
        for y in range(frame_height):
            for x in range(width):
                distance = min(x, y)
                pixels[x, origin_y + y] = (
                    rail[distance] if distance < EDGE_WIDTH else bed
                )
    return image


def render_high_visibility() -> Image.Image:
    image = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    pixels = image.load()
    width, frame_height = FRAME_SIZE
    for frame, (rail, bed) in enumerate((
            (HIGH_ATTACK_RAIL, HIGH_ATTACK_BED),
            (HIGH_PULSE_RAIL, HIGH_PULSE_BED))):
        origin_y = frame * frame_height
        for y in range(frame_height):
            for x in range(width):
                distance = min(x, y)
                pixels[x, origin_y + y] = (
                    rail[distance] if distance < HIGH_EDGE_WIDTH else bed
                )
    return image


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    save_tga(render(), OUTPUT)
    save_tga(render_high_visibility(), HIGH_OUTPUT)
    print(
        "Native auto-attack indicators painted: subtle five-layer default + "
        "opt-in nine-pixel pure-red high-visibility alternate"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
