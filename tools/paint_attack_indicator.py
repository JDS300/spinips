#!/usr/bin/env python3
"""Paint SpinUI's client-native auto-attack indicator texture.

EverQuest owns the visibility and flashing cadence of the four
``A_AttackIndicatorAnim*`` edge widgets in ``EQUI_PlayerWindow.xml``.  The
texture therefore remains a single, fully opaque pure-red frame just like the
working Modern UI contract.  Only narrow edge slices are drawn by the XML; the
fill widget is intentionally unbound so player information is never tinted.

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
COLOR = (255, 0, 0, 255)


def render() -> Image.Image:
    return Image.new("RGBA", SIZE, COLOR)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    save_tga(render(), OUTPUT)
    print(
        "AttackIndicator.tga: native pure-red attack rail painted | "
        "EverQuest-controlled flash | no fill wash"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
