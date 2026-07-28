#!/usr/bin/env python3
"""Repaint the combat-state icons in window_pieces06.tga.

The client renders these five 40x40 cells (column x=200) at DecalSize 13x13
on the player plate via the A_PWCS* animations in EQUI_PlayerWindow.xml.
The stock art collapses at that size: the red X reads as a smudge and the
hourglass reads as a solid triangle. These redraws use thick, high-contrast
shapes tuned for the 13px render:

    (200,   0) in-combat  -> crossed steel swords with gold guards
    (200,  40) debuff     -> purple skull
    (200,  80) timer      -> orange hourglass with full-width caps
    (200, 120) standing   -> blue ring
    (200, 160) regen      -> green plus

Each glyph is drawn 3x supersampled and downsampled for clean edges.
Idempotent: rewriting the same cells is a no-op byte-wise.
Run from repo root:  python3 tools/paint_combat_state_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
TGA = REPO / "spinui_reloaded" / "window_pieces06.tga"

OUTLINE = (5, 7, 10, 255)
STEEL = (204, 214, 222, 255)
GOLD = (250, 205, 95, 255)
PURPLE = (168, 100, 220, 255)
ORANGE = (240, 160, 52, 255)
BLUE = (86, 148, 244, 255)
GREEN = (74, 204, 118, 255)

S = 3          # supersample factor
CELL = 40


def _canvas():
    return Image.new("RGBA", (CELL * S, CELL * S), (0, 0, 0, 0))


def _finish(img):
    return img.resize((CELL, CELL), Image.LANCZOS)


def swords():
    img = _canvas()
    d = ImageDraw.Draw(img)
    a, b = 8 * S, 32 * S
    for (x0, y0, x1, y1) in ((a, a, b, b), (b, a, a, b)):
        d.line([(x0, y0), (x1, y1)], fill=OUTLINE, width=9 * S // 2)
    for (x0, y0, x1, y1) in ((a, a, b, b), (b, a, a, b)):
        d.line([(x0, y0), (x1, y1)], fill=STEEL, width=5 * S // 2)
    # gold crossguards near the lower ends
    d.line([(11 * S, 25 * S), (18 * S, 32 * S)], fill=GOLD, width=3 * S)
    d.line([(29 * S, 25 * S), (22 * S, 32 * S)], fill=GOLD, width=3 * S)
    return _finish(img)


def skull():
    img = _canvas()
    d = ImageDraw.Draw(img)
    d.ellipse([7 * S, 4 * S, 33 * S, 28 * S], fill=PURPLE, outline=OUTLINE,
              width=2 * S)
    d.rectangle([13 * S, 26 * S, 27 * S, 35 * S], fill=PURPLE,
                outline=OUTLINE, width=2 * S)
    for x in (12, 22):
        d.ellipse([x * S, 12 * S, (x + 7) * S, 20 * S], fill=OUTLINE)
    for x in (15, 20, 25):
        d.line([(x * S, 29 * S), (x * S, 35 * S)], fill=OUTLINE, width=S)
    return _finish(img)


def hourglass():
    img = _canvas()
    d = ImageDraw.Draw(img)
    # full-width caps keep it reading as an hourglass, not a triangle
    d.rectangle([5 * S, 3 * S, 35 * S, 8 * S], fill=ORANGE, outline=OUTLINE,
                width=S)
    d.rectangle([5 * S, 32 * S, 35 * S, 37 * S], fill=ORANGE, outline=OUTLINE,
                width=S)
    d.polygon([(8 * S, 8 * S), (32 * S, 8 * S), (22 * S, 20 * S),
               (18 * S, 20 * S)], fill=ORANGE, outline=OUTLINE)
    d.polygon([(18 * S, 20 * S), (22 * S, 20 * S), (32 * S, 32 * S),
               (8 * S, 32 * S)], fill=ORANGE, outline=OUTLINE)
    return _finish(img)


def ring():
    img = _canvas()
    d = ImageDraw.Draw(img)
    d.ellipse([5 * S, 5 * S, 35 * S, 35 * S], outline=OUTLINE, width=8 * S // 2)
    d.ellipse([7 * S, 7 * S, 33 * S, 33 * S], outline=BLUE, width=5 * S // 2)
    return _finish(img)


def plus():
    img = _canvas()
    d = ImageDraw.Draw(img)
    d.rectangle([15 * S, 4 * S, 25 * S, 36 * S], fill=GREEN, outline=OUTLINE,
                width=S)
    d.rectangle([4 * S, 15 * S, 36 * S, 25 * S], fill=GREEN, outline=OUTLINE,
                width=S)
    d.rectangle([15 * S, 15 * S, 25 * S, 25 * S], fill=GREEN)
    return _finish(img)


def main():
    img = Image.open(TGA).convert("RGBA")
    assert img.size == (256, 256), f"unexpected window_pieces06.tga size {img.size}"
    glyphs = (swords(), skull(), hourglass(), ring(), plus())
    for row, glyph in enumerate(glyphs):
        region = (200, row * 40)
        img.paste(Image.new("RGBA", (40, 40), (0, 0, 0, 0)), region)
        img.paste(glyph, region, glyph)
    img.save(TGA)
    print("window_pieces06.tga: combat-state glyphs repainted at (200,0..200)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
