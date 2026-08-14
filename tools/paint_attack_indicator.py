#!/usr/bin/env python3
"""Paint SpinUI's client-native auto-attack indicator texture.

EverQuest owns the visibility and flashing cadence of the five recognized
``A_AttackIndicatorAnim*`` widgets in ``EQUI_PlayerWindow.xml``. Narrow edge
slices use a fully opaque neutral-white rail; the required Fill widget uses a
transparent-center white perimeter. The client owns attack-on visibility,
red tint, and flashing cadence.

Run from the repository root:
    python tools/paint_attack_indicator.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "spinui_reloaded" / "AttackIndicator.tga"
RAIL_OUTPUT = REPO / "spinui_reloaded" / "SpinAttackRail.tga"
PERIMETER_OUTPUT = REPO / "spinui_reloaded" / "SpinAttackPerimeter.tga"
FRAME_SIZE = (128, 32)
SIZE = FRAME_SIZE
EDGE_WIDTH = 3
COLOR = (255, 255, 255, 255)


def render() -> Image.Image:
    return Image.new("RGBA", SIZE, COLOR)


def render_perimeter() -> Image.Image:
    image = Image.new("RGBA", SIZE, (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.line((0, 0, 0, SIZE[1] - 1), fill=COLOR, width=1)
    draw.line((SIZE[0] - 1, 0, SIZE[0] - 1, SIZE[1] - 1),
              fill=COLOR, width=1)
    draw.line((0, SIZE[1] - 1, SIZE[0] - 1, SIZE[1] - 1),
              fill=COLOR, width=1)
    return image


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # Retain the proven 32-bit RLE envelope used by the legacy renderer.
    rail = render()
    rail.save(OUTPUT, format="TGA", compression="tga_rle")
    rail.save(RAIL_OUTPUT, format="TGA", compression="tga_rle")
    render_perimeter().save(
        PERIMETER_OUTPUT, format="TGA", compression="tga_rle",
    )
    print(
        "Spin attack textures: native white rail + transparent-center "
        "foreground perimeter | client red flash | no fill wash"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
