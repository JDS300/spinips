#!/usr/bin/env python3
"""Paint SpinUI's client-native auto-attack indicator texture.

EverQuest owns the visibility and flashing cadence of the four
``A_AttackIndicatorAnim*`` edge widgets in ``EQUI_PlayerWindow.xml``.  The
texture therefore remains a single, fully opaque neutral frame like the
working Modern UI contract.  EverQuest modulates that neutral source from
white/gray to red; pre-coloring the source red destroys the visible flash
because every tint phase remains red.  Only narrow edge slices are drawn by
the XML, and the fill widget is intentionally unbound.

Run from the repository root:
    python tools/paint_attack_indicator.py
"""

from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "spinui_reloaded" / "AttackIndicator.tga"
FRAME_SIZE = (128, 32)
SIZE = FRAME_SIZE
EDGE_WIDTH = 8
# Keep the source neutral so EverQuest can still modulate it between its native
# white and red attack phases, but raise the luminance to health-bar intensity.
# The sub-white RLE envelope remains friendly to the legacy renderer while its
# red phase is vivid enough to remain unmistakable over either SpinUI theme.
COLOR = (245, 245, 245, 255)


def render() -> Image.Image:
    return Image.new("RGBA", SIZE, COLOR)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # RLE 32-bit is the known-working Modern TGA envelope.  For this solid
    # source Pillow emits a deterministic 204-byte file (type 10, alpha 8).
    render().save(OUTPUT, format="TGA", compression="tga_rle")
    print(
        "AttackIndicator.tga: native neutral RLE attack rail painted | "
        "8px high-luminance EverQuest tint-driven pulse | no fill wash"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
