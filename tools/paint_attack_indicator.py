#!/usr/bin/env python3
"""Paint SpinUI's native auto-attack outline.

EverQuest owns the visibility of the four ``A_AttackIndicatorAnim*`` pieces
in ``EQUI_PlayerWindow.xml``. They are hidden while auto-attack is off and
shown while it is on, so the indicator follows the client state directly and
does not need log parsing or combat heuristics.

The stock-named ``AttackIndicator.tga`` contains eight stacked 128x32 frames.
Each frame has a pure-red outline and a completely transparent interior. The
alpha sequence produces the quick, smooth flash used by modern unit frames:
bright -> dim -> bright in 560 ms. The canonical player frame samples four
pixels of the rail; the High-Visibility alternate samples five.

Run from the repository root:
    python tools/paint_attack_indicator.py
"""

from pathlib import Path

from PIL import Image

from generate_spinui_textures import save_tga


REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "spinui_reloaded" / "AttackIndicator.tga"
FRAME_SIZE = (128, 32)
FRAME_ALPHAS = (255, 230, 190, 140, 72, 140, 190, 230)
FRAME_ORIGINS = tuple(index * FRAME_SIZE[1]
                      for index in range(len(FRAME_ALPHAS)))
FRAME_DURATION_MS = 70
SIZE = (FRAME_SIZE[0], FRAME_SIZE[1] * len(FRAME_ALPHAS))
EDGE_WIDTH = 4
HIGH_EDGE_WIDTH = 5
TRANSPARENT = (0, 0, 0, 0)
FRAME_RAILS = tuple((255, 0, 0, alpha) for alpha in FRAME_ALPHAS)


def render() -> Image.Image:
    image = Image.new("RGBA", SIZE, TRANSPARENT)
    pixels = image.load()
    width, frame_height = FRAME_SIZE
    for origin_y, rail in zip(FRAME_ORIGINS, FRAME_RAILS):
        for y in range(frame_height):
            for x in range(width):
                if min(x, y) < HIGH_EDGE_WIDTH:
                    pixels[x, origin_y + y] = rail
    return image


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    save_tga(render(), OUTPUT)
    print(
        "AttackIndicator.tga: eight-frame pure-red outline pulse painted | "
        "transparent interior | 560 ms cycle"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
