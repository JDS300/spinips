#!/usr/bin/env python3
"""Render the current Loremaster expanded panel and Rune Seed for docs."""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from spinui_theme import (BG1, BG2, BG3, CYAN, EMBER, GOLD, GOLD_BRIGHT, GREEN,
                          LINE, PARCHMENT, TEXT, TEXT_DIM, VOID)

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "previews"
COG = Image.open(REPO / "loremaster" / "assets" /
                 "loremaster-cog.png").convert("RGBA")

BG = BG1
PANEL = BG2
RAISED = BG3
DIM = TEXT_DIM
LORE_HOTKEY = "CTRL+SHIFT+E"

# Deterministic documentation example, verified against the EQL Wiki
# MediaWiki wikitext endpoint for https://eqlwiki.com/Cloak_of_Flames.
CLOAK_OF_FLAMES = {
    "title": "Cloak of Flames",
    "profile": (
        ("MAGIC ITEM", CYAN),
        ("Slot: BACK", TEXT),
        ("AC: 10", TEXT),
        ("DEX: +9   AGI: +9   HP: +50", TEXT),
        ("SV FIRE: +15", TEXT),
        ("Haste: +36%", TEXT),
        ("WT: 0.1   Size: MEDIUM", TEXT),
        ("Class: ALL   Race: ALL", TEXT),
    ),
    "drops": (("Nagafen's Lair", "Lord Nagafen"),),
}


def font_path(*names):
    roots = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")]
    for root in roots:
        for name in names:
            path = root / name
            if path.exists():
                return path
    return None


SANS = font_path("segoeui.ttf", "DejaVuSans.ttf")
BOLD = font_path("seguisb.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf")
SERIF = font_path("georgiab.ttf", "DejaVuSerif-Bold.ttf")
SYMBOL = font_path("seguisym.ttf", "DejaVuSans.ttf")


def F(size, bold=False, serif=False):
    path = SERIF if serif else (BOLD if bold else SANS)
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default()


def FS(size):
    return ImageFont.truetype(str(SYMBOL), size) if SYMBOL else F(size)


def hexagon(draw, cx, cy, radius, color, width=1, inner=False):
    pts = [(cx + radius * math.cos(math.radians(90 + i * 60)),
            cy + radius * math.sin(math.radians(90 + i * 60))) for i in range(7)]
    draw.line(pts, fill=color, width=width, joint="curve")
    if inner:
        draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=EMBER)


def paste_cog(draw, cx, cy):
    surface = draw._image
    surface.paste(COG, (round(cx - COG.width / 2),
                        round(cy - COG.height / 2)), COG)


def rune_seed(draw, x, y, value="1.28k", label="DPS", state="live",
              width=92, height=48):
    """Draw the canvas-rendered Rune Seed vocabulary used by the Tk overlay."""
    states = {
        "idle": (GOLD, LINE, LINE, "\u2014"),
        "live": (CYAN, GREEN, LINE, value),
        "alert": ((222, 62, 72), EMBER, (222, 62, 72), "!"),
        "stale": (LINE, LINE, LINE, value),
    }
    left, right, edge, shown = states.get(state, states["live"])
    scale = height / 48
    radius = max(8, round(13 * scale))
    draw.rounded_rectangle(
        [x + 2 * scale, y + 3 * scale,
         x + width - scale, y + height - scale],
        radius=radius, fill=VOID)
    draw.rounded_rectangle(
        [x + scale, y + scale, x + width - 2 * scale,
         y + height - 3 * scale], radius=radius,
        fill=PANEL, outline=edge, width=max(1, round(scale)))
    draw.line([(x + 16 * scale, y + 3 * scale),
               (x + width - 14 * scale, y + 3 * scale)], fill=LINE)
    center_x, center_y = x + 23 * scale, y + height / 2
    draw.ellipse([center_x - 18, center_y - 18,
                  center_x + 18, center_y + 18], outline=edge,
                 width=max(1, round(scale)))
    paste_cog(draw, center_x, center_y)
    text_left = max(center_x + 21, x + 45 * scale)
    text_x = (text_left + x + width - 4 * scale) / 2
    if value or label:
        draw.text((text_x, y + 16 * scale), shown,
                  font=F(max(7, round(14 * scale)), bold=True),
                  fill=TEXT, anchor="mm")
        draw.text((text_x, y + 31 * scale),
                  "CHARM" if state == "alert" else label,
                  font=F(max(5, round(7 * scale)), bold=True),
                  fill=EMBER if state == "alert" else GOLD_BRIGHT,
                  anchor="mm")
    if width >= 70:
        for index in range(4):
            px = text_x - 7.5 * scale + index * 5 * scale
            draw.ellipse([px - scale, y + 40.5 * scale,
                          px + scale, y + 42.5 * scale],
                         fill=GOLD_BRIGHT if index == 0 else LINE)


def section(draw, width, y, name, value, pinned, expanded=False):
    accent = CYAN if expanded else LINE
    hexagon(draw, 19, y + 9, 6, accent)
    draw.text((31, y + 9), name, font=F(9, bold=True, serif=True),
              fill=accent if expanded else TEXT_DIM, anchor="lm")
    draw.text((width - 57, y + 9), value, font=F(11, bold=True), fill=TEXT, anchor="rm")
    draw.text((width - 39, y + 9), "✦" if pinned else "◇", font=FS(10),
              fill=GOLD_BRIGHT if pinned else LINE, anchor="mm")
    draw.text((width - 18, y + 9), "▾" if expanded else "▸", font=FS(9), fill=DIM, anchor="mm")
    draw.line([(12, y + 20), (width - 12, y + 20)], fill=accent)
    draw.line([(12, y + 21), (width - 12, y + 21)], fill=(5, 6, 9))
    return y + 27


def render_lore_lens():
    """Render the item-intelligence companion shown beside EQ's tooltip."""
    width, height = 392, 560
    lens = Image.new("RGB", (width, height), GOLD)
    d = ImageDraw.Draw(lens)
    d.rectangle([1, 1, width - 2, height - 2], fill=BG)

    d.rectangle([2, 2, width - 3, 34], fill=PANEL)
    d.rectangle([2, 2, 5, 34], fill=CYAN)
    d.text((14, 18), "LORE LENS", font=F(10, serif=True),
           fill=GOLD_BRIGHT, anchor="lm")
    d.text((width - 34, 18), f"{LORE_HOTKEY}  •  SETTINGS",
           font=F(6, serif=True),
           fill=DIM, anchor="rm")
    d.text((width - 12, 18), "×", font=F(10, bold=True), fill=DIM, anchor="mm")

    d.rectangle([10, 43, width - 10, 72], fill=RAISED)
    d.rectangle([12, 46, width - 89, 69], fill=VOID, outline=LINE)
    d.text((19, 58), CLOAK_OF_FLAMES["title"], font=F(9), fill=TEXT, anchor="lm")
    d.rectangle([width - 84, 46, width - 13, 69], fill=PANEL, outline=LINE)
    d.text((width - 48, 58), "SEARCH", font=F(7, serif=True),
           fill=GOLD_BRIGHT, anchor="mm")

    y = 84
    d.text((14, y), CLOAK_OF_FLAMES["title"].upper(), font=F(13, serif=True),
           fill=GOLD_BRIGHT)
    y += 27
    d.text((14, y), "ITEM PROFILE", font=F(7, serif=True), fill=GOLD)
    y += 17
    for line, color in CLOAK_OF_FLAMES["profile"]:
        d.text((14, y), line, font=F(8, bold=(color == CYAN)), fill=color)
        y += 15

    d.text((14, y + 4), "DROPS FROM", font=F(7, serif=True), fill=GOLD)
    y += 24
    for zone, creature in CLOAK_OF_FLAMES["drops"]:
        d.text((14, y), zone, font=F(8, bold=True), fill=GOLD_BRIGHT)
        y += 14
        d.text((26, y), "• " + creature, font=F(8), fill=TEXT)
        y += 16

    for heading, empty in (
        ("SOLD BY", "This item cannot be purchased from merchants."),
        ("RELATED QUESTS", "This item has no related quests."),
        ("PLAYER CRAFTED", "This item is not crafted by players."),
        ("TRADESKILL RECIPES", "This item is not used in player tradeskills."),
    ):
        d.text((14, y), heading, font=F(7, serif=True), fill=GOLD)
        y += 15
        d.text((14, y), empty, font=F(7), fill=DIM)
        y += 19

    d.rectangle([2, height - 53, width - 3, height - 24], fill=PANEL)
    d.text((10, height - 39), "EQL WIKI  •  CACHED JUST NOW", font=F(7, serif=True),
           fill=DIM, anchor="lm")
    d.rectangle([width - 153, height - 49, width - 8, height - 28],
                fill=RAISED, outline=LINE)
    d.text((width - 86, height - 39), "OPEN FULL WIKI PAGE",
           font=F(7, serif=True), fill=CYAN, anchor="mm")
    d.text((width - 19, height - 39), "↗", font=FS(8), fill=CYAN,
           anchor="mm")
    d.text((width // 2, height - 12),
           "SAFE LOOKUP  •  CLIPBOARD OR SEARCH  •  NO EQ INJECTION",
           font=F(6, serif=True), fill=LINE, anchor="mm")
    return lens


def render_seed_showcase():
    width, height = 720, 230
    image = Image.new("RGB", (width, height), VOID)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([0, 0, width - 1, height - 1], radius=18,
                           fill=VOID, outline=LINE)
    draw.text((24, 25), "RUNE SEED · 92 × 48", font=F(10, serif=True),
              fill=GOLD)
    draw.text((width - 24, 25), "EXPANDED · 550 × 820",
              font=F(8, serif=True), fill=DIM, anchor="ra")
    draw.text((24, 49), "scroll starred metrics · click to unfold · drag when unlocked",
              font=F(8), fill=DIM)
    for index, (state, caption) in enumerate((
            ("idle", "IDLE"), ("live", "LIVE"),
            ("alert", "ALERT"), ("stale", "STALE"))):
        x = 26 + index * 105
        rune_seed(draw, x, 78, state=state)
        draw.text((x + 46, 137), caption, font=F(7, serif=True),
                  fill=CYAN if state == "live" else EMBER if state == "alert" else DIM,
                  anchor="mm")
    draw.rounded_rectangle([498, 74, 692, 132], radius=13,
                           fill=BG, outline=(95, 39, 37))
    draw.ellipse([508, 88, 536, 116], outline=(222, 62, 72), width=2)
    draw.arc([505, 85, 539, 119], 35, 120, fill=EMBER, width=2)
    draw.text((522, 102), "!", font=F(13, bold=True), fill=EMBER, anchor="mm")
    draw.text((547, 94), "DANGER ALERT", font=F(7, serif=True), fill=EMBER)
    draw.text((547, 115), "BIG HIT · 3,942", font=F(11, bold=True), fill=TEXT)
    draw.text((24, 184), "MORPH", font=F(7, serif=True), fill=GOLD)
    rune_seed(draw, 87, 166, width=60, height=38)
    draw.line([(158, 185), (196, 185)], fill=LINE, width=2)
    draw.polygon([(196, 181), (204, 185), (196, 189)], fill=LINE)
    draw.rounded_rectangle([220, 160, 340, 210], radius=18,
                           fill=BG, outline=LINE)
    draw.arc([229, 168, 265, 204], 30, 300, fill=CYAN, width=3)
    draw.text((278, 177), "LORE LENS", font=F(6, serif=True), fill=GOLD)
    draw.text((278, 195), "1,284 DPS", font=F(10, bold=True), fill=TEXT)
    draw.text((374, 187), "240 ms · time-sampled motion · reduced motion: instant",
              font=F(8), fill=DIM)
    return image


def render_mez_overlay():
    """Render the live three-row crowd-control stack at documentation scale."""
    width = 612
    header_height = 54
    row_height = 82
    height = header_height + row_height * 3 + 2
    image = Image.new("RGB", (width, height), GOLD)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([1, 1, width - 2, height - 2], radius=15,
                           fill=BG, outline=GOLD)
    draw.rectangle([2, 2, width - 3, 5], fill=CYAN)
    draw.rectangle([2, 6, width - 3, header_height], fill=PANEL)
    draw.text((20, 31), "CONTROL  ·  MEZ", font=F(15, serif=True),
              fill=CYAN, anchor="lm")
    draw.text((width - 20, 31), "5 TRACKED \u00b7 +1", font=F(14),
              fill=DIM, anchor="rm")

    rows = (
        ("a thought spoiler \u00d72", "Mesmerization V", "18s", "SAFE",
         CYAN, .42),
        ("an elite gnoll shaman", "Enthrall II", "8s", "SAFE",
         GOLD_BRIGHT, .17),
        ("Sabertooth Overseer", "Mesmerize III", "LAST TICK", "WAKE WINDOW",
         EMBER, 0.0),
    )
    for index, (target, spell, remaining, phase, color, fraction) in enumerate(rows):
        top = header_height + index * row_height
        bottom = top + row_height
        if index:
            draw.line([(2, top), (width - 3, top)], fill=LINE)
        draw.rectangle([2, top, 6, bottom - 1], fill=color)
        draw.text((22, top + 27), target, font=F(19, bold=True),
                  fill=PARCHMENT, anchor="lm")
        draw.text((22, top + 55), spell, font=F(14), fill=DIM, anchor="lm")
        draw.text((width - 20, top + 27), remaining,
                  font=F(20, bold=True), fill=color, anchor="rm")
        draw.text((width - 20, top + 55), phase, font=F(12, serif=True),
                  fill=color if phase != "SAFE" else DIM, anchor="rm")
        meter_top = bottom - 4
        draw.rectangle([7, meter_top, width - 3, bottom - 2], fill=LINE)
        if fraction:
            meter_right = 7 + round((width - 10) * fraction)
            draw.rectangle([7, meter_top, meter_right, bottom - 2], fill=color)
    return image


def main():
    # Matches Loremaster's FULL_DEFAULT_SIZE exactly.
    width, height = 550, 820
    panel = Image.new("RGB", (width, height), GOLD)
    d = ImageDraw.Draw(panel)
    d.rounded_rectangle([1, 1, width - 2, height - 2], radius=18,
                        fill=BG, outline=LINE)

    # Rune-anchored masthead.
    d.rounded_rectangle([2, 2, width - 3, 70], radius=17, fill=RAISED)
    d.rectangle([2, 52, width - 3, 70], fill=RAISED)
    paste_cog(d, 35, 35)
    d.text((72, 27), "LOREMASTER", font=F(14, serif=True),
           fill=PARCHMENT)
    d.ellipse([72, 45, 80, 53], fill=GREEN)
    d.text((86, 49), "LIVE · 38s", font=F(8, bold=True), fill=GREEN, anchor="lm")
    d.text((width - 14, 35), "RESET   LORE   SEED   —   ○   ×",
           font=F(8, serif=True), fill=DIM, anchor="rm")
    d.line([(2, 70), (width - 3, 70)], fill=LINE)

    # Identity and scope.
    d.text((20, 92), "SPIN · 67 · ENC / CLR / MAG", font=F(8, serif=True),
           fill=PARCHMENT)
    d.text((width - 20, 92), "The Dreadlands · session 1h44m",
           font=F(8), fill=DIM, anchor="ra")
    d.rounded_rectangle([18, 106, width - 18, 143], radius=10,
                        fill=VOID, outline=LINE)
    tab_width = (width - 36) / 3
    d.rounded_rectangle([22, 110, int(18 + tab_width), 139], radius=8,
                        fill=RAISED, outline=LINE)
    for index, label in enumerate(("ENCOUNTER", "SESSION", "RECORDS")):
        d.text((18 + tab_width * (index + .5), 125), label,
               font=F(8, serif=True), fill=TEXT if index == 0 else DIM,
               anchor="mm")

    d.text((22, 161), "‹ PREVIOUS", font=F(7, serif=True), fill=CYAN)
    d.text((width // 2, 161), "AN ABHORRENT · CURRENT FIGHT",
           font=F(8, serif=True), fill=GOLD, anchor="ma")
    d.text((width - 22, 161), "NEXT ›", font=F(7, serif=True),
           fill=LINE, anchor="ra")

    # Encounter hero and cached meter.
    hero_top, hero_bottom = 174, 302
    d.rounded_rectangle([18, hero_top, width - 18, hero_bottom], radius=14,
                        fill=RAISED, outline=LINE)
    d.text((34, 198), "1,284", font=F(34, bold=True), fill=GOLD_BRIGHT)
    d.text((158, 218), "DPS", font=F(8, serif=True), fill=GOLD)
    d.line([(270, 190), (270, 258)], fill=LINE)
    d.text((292, 198), "SESSION", font=F(7, serif=True), fill=DIM)
    d.text((292, 225), "946", font=F(17, bold=True), fill=PARCHMENT)
    d.text((414, 198), "BEST", font=F(7, serif=True), fill=DIM)
    d.text((414, 225), "2,105", font=F(17, bold=True), fill=PARCHMENT)
    d.text((292, 249), "Previous 812 · Next —", font=F(7), fill=DIM)
    d.rounded_rectangle([34, 270, width - 34, 278], radius=4,
                        fill=(46, 28, 16), outline=(76, 44, 24))
    d.rounded_rectangle([34, 270, 376, 278], radius=4, fill=CYAN)
    d.text((34, 290), "71% of personal best", font=F(7), fill=DIM)
    d.text((width - 34, 290), "00:38", font=F(7), fill=DIM, anchor="ra")

    # Quick metrics.
    quick_y = 314
    cell_gap = 6
    cell_width = (width - 36 - cell_gap * 3) // 4
    for index, (label, value) in enumerate((
            ("DAMAGE", "48.8k"), ("TAKEN", "1.9k"),
            ("HEALING", "3.2k"), ("ENEMIES", "7"))):
        x0 = 18 + index * (cell_width + cell_gap)
        d.rounded_rectangle([x0, quick_y, x0 + cell_width, quick_y + 57],
                            radius=9, fill=VOID, outline=LINE)
        d.text((x0 + 11, quick_y + 17), label, font=F(6, serif=True), fill=DIM)
        d.text((x0 + 11, quick_y + 43), value, font=F(14, bold=True), fill=TEXT)

    # Parse pivots and contributors.
    tab_y = 390
    labels = ("OVERVIEW", "DAMAGE", "HEALING", "TARGETS", "TIMELINE")
    lab_width = (width - 36) / len(labels)
    for index, label in enumerate(labels):
        x = 18 + lab_width * (index + .5)
        d.text((x, tab_y + 12), label, font=F(7, serif=True),
               fill=TEXT if label == "DAMAGE" else DIM, anchor="mm")
    d.line([(18 + lab_width, tab_y + 27),
            (18 + lab_width * 2, tab_y + 27)], fill=GOLD, width=2)

    content_top = 428
    d.rounded_rectangle([18, content_top, width - 18, content_top + 112],
                        radius=11, fill=VOID, outline=LINE)
    d.text((32, content_top + 22), "CONTRIBUTORS", font=F(8, serif=True),
           fill=GOLD)
    d.text((width - 32, content_top + 22), "TOTAL · SHARE · DPS",
           font=F(7), fill=DIM, anchor="ra")
    for row, (name, value, share, color) in enumerate((
            ("Spin", "32.4k · 66% · 1,284", .66, CYAN),
            ("An abhorrent (pet)", "16.4k · 34% · 648", .34, GOLD))):
        y = content_top + 54 + row * 35
        d.ellipse([32, y - 5, 42, y + 5], fill=color)
        d.text((50, y), name, font=F(8, bold=(row == 0)),
               fill=TEXT if row == 0 else PARCHMENT, anchor="lm")
        d.rounded_rectangle([210, y - 4, 390, y + 4], radius=4,
                            fill=(46, 28, 16))
        d.rounded_rectangle([210, y - 4, 210 + int(180 * share), y + 4],
                            radius=4, fill=color)
        d.text((width - 32, y), value, font=F(7),
               fill=TEXT if row == 0 else PARCHMENT, anchor="rm")

    # Card ledger: the real panel keeps these expandable and scrollable.
    d.text((20, 558), "THE LEDGER", font=F(9, serif=True), fill=GOLD)
    d.text((width - 20, 558), "STAR TO PIN IN SEED ☆", font=F(7),
           fill=DIM, anchor="ra")
    for index, (label, value, pinned) in enumerate((
            ("SLAYING", "47", True), ("SPOILS", "23", False),
            ("COIN", "2p 9g", False), ("PROGRESS", "+18.6%", True))):
        y = 570 + index * 30
        d.rounded_rectangle([18, y, width - 18, y + 27], radius=7,
                            fill=VOID, outline=LINE)
        hexagon(d, 34, y + 13, 5, CYAN if index == 0 else LINE)
        d.text((48, y + 13), label, font=F(7, serif=True),
               fill=CYAN if index == 0 else DIM, anchor="lm")
        d.text((width - 54, y + 13), value, font=F(10, bold=True),
               fill=GREEN if label == "PROGRESS" else TEXT, anchor="rm")
        d.text((width - 32, y + 13), "✦" if pinned else "◇", font=FS(9),
               fill=GOLD_BRIGHT if pinned else LINE, anchor="mm")

    # Expanded alert rail.
    rail_y = 696
    d.rounded_rectangle([18, rail_y, width - 18, rail_y + 58], radius=11,
                        fill=RAISED, outline=(105, 59, 31))
    d.ellipse([31, rail_y + 21, 43, rail_y + 33], fill=GREEN)
    d.text((52, rail_y + 20), "ALERTS ON", font=F(7, serif=True), fill=GOLD)
    d.text((52, rail_y + 40), "6 armed · click to tune", font=F(7), fill=DIM)
    chip_x = 224
    for label, active in (("CHARM", True), ("TELL", True), ("BIG HIT", True)):
        chip_w = 66 if label != "BIG HIT" else 78
        d.rounded_rectangle([chip_x, rail_y + 16, chip_x + chip_w, rail_y + 44],
                            radius=14, fill=BG,
                            outline=(222, 62, 72) if label == "BIG HIT" else LINE)
        d.text((chip_x + chip_w // 2, rail_y + 30), label,
               font=F(6, serif=True), fill=GOLD_BRIGHT if active else DIM,
               anchor="mm")
        chip_x += chip_w + 7
    d.rounded_rectangle([chip_x, rail_y + 16, chip_x + 34, rail_y + 44],
                        radius=14, fill=BG, outline=LINE)
    d.text((chip_x + 17, rail_y + 30), "⚙", font=FS(8), fill=DIM, anchor="mm")

    # Persistent operational controls.
    d.line([(2, 767), (width - 3, 767)], fill=LINE)
    d.ellipse([18, 783, 25, 790], fill=GREEN)
    d.text((31, 787), "log live · 4 Hz", font=F(7), fill=DIM, anchor="lm")
    d.text((width - 20, 787), "LOCK   CLICK-THROUGH   SETTINGS   ↘",
           font=F(7, serif=True), fill=PARCHMENT, anchor="rm")
    d.rounded_rectangle([18, 801, width - 18, 816], radius=7, fill=VOID)
    d.text((28, 809), "Fight · Session · Records / Overview · Damage · Healing · Targets · Timeline",
           font=F(6), fill=DIM, anchor="lm")

    lore_lens = render_lore_lens()
    seed_showcase = render_seed_showcase()
    mez_overlay = render_mez_overlay()
    OUT.mkdir(parents=True, exist_ok=True)
    canvas_width = width * 2 + lore_lens.width * 2 + 120
    canvas_height = max(1816, height * 2 + 80,
                        lore_lens.height * 2 + seed_showcase.height + 140)
    canvas = Image.new("RGB", (canvas_width, canvas_height), (26, 24, 30))
    canvas.paste(panel.resize((width * 2, height * 2), Image.Resampling.LANCZOS),
                 (40, 40))
    right_x = width * 2 + 80
    canvas.paste(lore_lens.resize((lore_lens.width * 2, lore_lens.height * 2),
                                  Image.Resampling.LANCZOS),
                 (right_x, 40))
    canvas.paste(seed_showcase, (right_x, lore_lens.height * 2 + 80))
    mez_x = right_x + (lore_lens.width * 2 - mez_overlay.width) // 2
    canvas.paste(mez_overlay, (mez_x, lore_lens.height * 2 + 340))
    canvas.save(OUT / "loremaster_panel.png")
    print("wrote docs/previews/loremaster_panel.png")


if __name__ == "__main__":
    main()
