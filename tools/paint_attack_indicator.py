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

from generate_spinui_textures import save_tga


REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "spinui_reloaded" / "AttackIndicator.tga"
FRAME_SIZE = (128, 32)
SIZE = FRAME_SIZE
EDGE_WIDTH = 5
# Modern uses 189 gray.  Full neutral white preserves the same native tint
# animation while raising its red peak to 255 for dark Reloaded/Glass frames.
COLOR = (255, 255, 255, 255)


def render() -> Image.Image:
    return Image.new("RGBA", SIZE, COLOR)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    save_tga(render(), OUTPUT)
    print(
        "AttackIndicator.tga: full-bright neutral attack rail painted | "
        "EverQuest tint-driven red flash | no fill wash"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
