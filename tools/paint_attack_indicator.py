#!/usr/bin/env python3
"""Paint SpinUI's native auto-attack indicator as a restrained red edge.

EverQuest owns the visibility of the four ``A_AttackIndicatorAnim*`` pieces
in ``EQUI_PlayerWindow.xml``.  They are hidden while auto-attack is off and
shown while it is on, so the texture is a reliable client-state indicator and
does not need log parsing or combat heuristics.

The horizontal pieces sample the first two rows of ``AttackIndicator.tga``;
the vertical pieces sample its first two columns.  A bright outer ember and a
deeper inner crimson create a crisp two-pixel glow without painting over the
health, mana, endurance, experience, or AA information.

Run from the repository root:
    python tools/paint_attack_indicator.py
"""

from pathlib import Path

from PIL import Image

from generate_spinui_textures import save_tga


REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "spinui_reloaded" / "AttackIndicator.tga"
SIZE = (128, 32)

ATTACK_EDGE = (242, 64, 60, 255)
ATTACK_INNER = (142, 22, 29, 255)
ATTACK_BED = (54, 7, 12, 255)


def render() -> Image.Image:
    image = Image.new("RGBA", SIZE, ATTACK_BED)
    pixels = image.load()
    width, height = SIZE
    for y in range(height):
        for x in range(width):
            distance = min(x, y)
            if distance == 0:
                pixels[x, y] = ATTACK_EDGE
            elif distance == 1:
                pixels[x, y] = ATTACK_INNER
    return image


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    save_tga(render(), OUTPUT)
    print(
        "AttackIndicator.tga: native auto-attack edge painted "
        f"{SIZE[0]}x{SIZE[1]} ember/crimson"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
