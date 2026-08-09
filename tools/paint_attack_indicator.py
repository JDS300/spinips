#!/usr/bin/env python3
"""Paint SpinUI's native auto-attack indicator as a vivid red edge.

EverQuest owns the visibility of the four ``A_AttackIndicatorAnim*`` pieces
in ``EQUI_PlayerWindow.xml``.  They are hidden while auto-attack is off and
shown while it is on, so the texture is a reliable client-state indicator and
does not need log parsing or combat heuristics.

The horizontal pieces sample the first five rows of ``AttackIndicator.tga``;
the vertical pieces sample its first five columns. A hot outer highlight,
vivid crimson core, and graduated red halo create a clear five-pixel combat
rail around the entire command frame. The remaining texture is a restrained
translucent wash, making the ON state unmistakable without obscuring health,
mana, endurance, experience, or AA information.

Run from the repository root:
    python tools/paint_attack_indicator.py
"""

from pathlib import Path

from PIL import Image

from generate_spinui_textures import save_tga


REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "spinui_reloaded" / "AttackIndicator.tga"
SIZE = (128, 32)
EDGE_WIDTH = 5

ATTACK_EDGE = (255, 184, 164, 255)
ATTACK_INNER = (255, 52, 58, 255)
ATTACK_HALO = (255, 8, 34, 255)
ATTACK_SOFT = (224, 0, 28, 238)
ATTACK_FADE = (174, 0, 22, 208)
ATTACK_BED = (126, 0, 16, 78)
ATTACK_RAIL = (
    ATTACK_EDGE,
    ATTACK_INNER,
    ATTACK_HALO,
    ATTACK_SOFT,
    ATTACK_FADE,
)


def render() -> Image.Image:
    image = Image.new("RGBA", SIZE, ATTACK_BED)
    pixels = image.load()
    width, height = SIZE
    for y in range(height):
        for x in range(width):
            distance = min(x, y)
            if distance < EDGE_WIDTH:
                pixels[x, y] = ATTACK_RAIL[distance]
    return image


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    save_tga(render(), OUTPUT)
    print(
        "AttackIndicator.tga: native auto-attack edge painted "
        f"{SIZE[0]}x{SIZE[1]} five-layer ember/crimson"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
