#!/usr/bin/env python3
"""Render the native-layout Glass Codex for visual regression review."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import render_preview as ui  # noqa: E402
from spinui_glass_theme import FROST, FROST_DIM, ICE, ICE_BRIGHT, MINT, VIOLET  # noqa: E402


SKIN = REPO / "spinui_glass"
OUT = REPO / "docs" / "previews" / "spinui_glass_spellbook.png"


def book_surface() -> Image.Image:
    book = Image.new("RGBA", (512, 363), (0, 0, 0, 0))
    for name, position in (
        ("default_spellbook01.tga", (0, 0)),
        ("default_spellbook02.tga", (256, 0)),
        ("default_spellbook03.tga", (0, 256)),
        ("default_spellbook04.tga", (256, 256)),
    ):
        book.alpha_composite(Image.open(SKIN / name).convert("RGBA"), position)

    draw = ImageDraw.Draw(book)
    slot = Image.open(SKIN / "window_pieces01.tga").convert("RGBA").crop(
        (130, 170, 178, 218))
    names = (
        "Mesmerization", "Allure", "Tashania", "Theft of Thought",
        "Wandering Mind", "Invisibility", "Divine Might", "Gasping Embrace",
        "Weakness", "Nullify Magic", "Shiftless Deeds", "Superior Healing",
        "Blanket of Forgetfulness", "Celerity", "Berserker Strength", "Charm",
    )
    colors = (
        VIOLET, (82, 130, 185), (180, 130, 88), VIOLET,
        (121, 76, 177), (90, 97, 109), (66, 80, 130), (158, 74, 72),
        (184, 76, 72), (120, 48, 50), (166, 70, 82), (210, 62, 74),
        (185, 144, 64), ICE, (120, 74, 150), MINT,
    )
    positions: list[tuple[int, int]] = []
    for page_x in (0, 256):
        for row in range(4):
            positions.extend(((page_x + 25, 24 + row * 72),
                              (page_x + 116, 24 + row * 72)))
    for index, ((x, y), name, color) in enumerate(zip(positions, names, colors), 1):
        book.alpha_composite(slot, (x, y))
        draw.rounded_rectangle([x + 5, y + 5, x + 42, y + 42], radius=4,
                               fill=color + (230,), outline=ICE_BRIGHT + (105,))
        draw.line([(x + 8, y + 8), (x + 38, y + 8)], fill=(255, 255, 255, 45))
        draw.text((x + 23, y + 50), name, font=ui.F(7, True), fill=FROST,
                  anchor="ma")
        if index in (1, 16):
            draw.ellipse([x + 34, y + 34, x + 43, y + 43],
                         fill=MINT + (255,), outline=ICE_BRIGHT + (255,))

    draw.text((92, 8), "01", font=ui.F(8, True), fill=FROST_DIM, anchor="ma")
    draw.text((420, 8), "02", font=ui.F(8, True), fill=FROST_DIM, anchor="ma")
    return book


def main() -> None:
    width, height = 1240, 880
    world = Image.new("RGBA", (width, height), (14, 20, 26, 255))
    draw = ImageDraw.Draw(world)
    for y in range(height):
        amount = y / height
        draw.line([(0, y), (width, y)],
                  fill=(round(16 + 10 * amount), round(23 + 14 * amount),
                        round(29 + 13 * amount), 255))
    glow = Image.new("RGBA", (760, 760), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([0, 0, 759, 759], fill=(46, 190, 200, 52))
    world.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)), (210, 20))
    violet = Image.new("RGBA", (560, 560), (0, 0, 0, 0))
    ImageDraw.Draw(violet).ellipse([0, 0, 559, 559], fill=VIOLET + (42,))
    world.alpha_composite(violet.filter(ImageFilter.GaussianBlur(100)), (560, 180))

    draw = ImageDraw.Draw(world)
    draw.text((width // 2, 46), "SPINUI GLASS CODEX", font=ui.F(30, True),
              fill=FROST, anchor="ma")
    draw.text((width // 2, 86), "native spellbook geometry - etched midnight glass",
              font=ui.F(14), fill=FROST_DIM, anchor="ma")
    draw.line([(330, 110), (910, 110)], fill=ICE + (110,))
    draw.line([(500, 112), (740, 112)], fill=MINT + (125,))

    book = book_surface().resize((1024, 726), Image.Resampling.NEAREST)
    world.alpha_composite(book, ((width - 1024) // 2, 132))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    world.convert("RGB").save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
