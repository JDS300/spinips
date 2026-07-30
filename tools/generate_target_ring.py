#!/usr/bin/env python3
"""Spin's UI Reloaded — "Vellum & Ember" target ring.

EverQuest builds the ring under your target procedurally: concentric circles of
vertices with one repeating texture scrolled inward, drawn additively and tinted
per consider colour.  The stock skin ships a flat sheet of grey noise there, so
every con reads as the same milky smear on the ground and the only difference
between "harmless" and "will kill you" is a hue the world lighting washes out.

This generator writes SpinUI's own ring sheet: a near-black field (invisible
under additive blending) carrying crisp concentric rings — a bright core, a
soft glow, and a dim hairline between each pair — that the client scrolls
inward. Structure lives on the radial axis only; see the RING_* block below for
why, and for what happens when it does not. The sheet stays neutral grey so
`TargetIndicator.ini` owns every colour.

Run from the repo root:  python3 tools/generate_target_ring.py

The companion ramp lives in spinui_reloaded/TargetIndicator.ini, which encodes
threat five ways at once — hue, opacity, inward speed, ring count, and radius —
so the ring stays legible for colour-blind players and in blown-out daylight.
"""

from __future__ import annotations

import argparse
import math
import struct
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIN = REPO / "spinui_reloaded"
PREVIEW_DIR = REPO / "docs" / "previews"

SIZE = 256

# --- Which way the sheet lies on the ring ----------------------------------
# The client builds the indicator as concentric circles of vertices and walks
# the sheet outward along them, scrolling it back towards the center: U runs
# once around the circumference, V runs radially.  So a *row* of this sheet is
# a circle drawn on the ground, and a *column* is a spoke.
#
# The first SpinUI sheet carried a lattice on both axes - rings across V plus
# ticks and bright nodes across U - and in game the U structure is what showed
# up: bright streaks radiating out of the target instead of rings around it.
# Structure therefore belongs on V alone.  U gets nothing but a whisper of
# brightness modulation, far too shallow to read as a spoke.
#
# Only powers of two tile 256 seamlessly, so the ring pitch is 16 rows.  The
# client shows TextureScale x 256 rows at once, which is why the ini's scale
# ramp doubles as a ring-count ramp: 0.10 shows ~1.6 rings, 0.24 shows ~3.8.
RING_PERIOD = 16
RING_CORE = 1.5           # half-width of a ring's bright core, in rows
RING_FALLOFF = 5.0        # how far a ring's glow reaches
HAIRLINE_OFFSET = RING_PERIOD / 2
ANGULAR_LOBES = 6         # integer cycles, so U stays seamless
ANGULAR_DEPTH = 0.07      # +/- 7%: life around the ring, never a spoke

BASE = 18                 # faint ground glow so the ring never disappears
RING_PEAK = 240
HAIRLINE_PEAK = 96

# Threat ramp shared by the generated preview and TargetIndicator.ini.  Each
# tier repeats its meaning in four channels: hue, opacity, inward drift, and
# how many rings are visible at once.
CON_TIERS = (
    # key, label, rgb, alpha, texture_scale, texture_speed, fade_end, twist
    ("Trivial", "TRIVIAL", (108, 116, 124), 140, 0.100, 0.0004, 16, 0.0),
    ("VeryEasy", "VERY EASY", (96, 214, 132), 175, 0.120, 0.0006, 17, 0.0),
    ("Easy", "EASY", (104, 206, 224), 195, 0.140, 0.0008, 18, 0.0),
    ("FairlyEasy", "FAIRLY EASY", (108, 150, 248), 212, 0.160, 0.0010, 19, 0.0),
    ("FairMatch", "EVEN MATCH", (244, 236, 214), 232, 0.180, 0.0013, 20, 0.0),
    ("Difficult", "DIFFICULT", (248, 196, 96), 248, 0.210, 0.0018, 21, 0.0),
    # Only the tier that can kill you pulses; see [instructions] for how to
    # switch it off without losing the rest of the ramp.
    ("Deadly", "DEADLY", (250, 82, 74), 255, 0.240, 0.0026, 22, 0.18),
)

# Non-con rings.  Free/FreeInvalid are the ground-target reticle and keep the
# client's own FreeTarget sheet; the raid Marker sections are left byte-for-byte
# as the client shipped them because their Mark*.tga art resolves outside this
# skin folder.
POINT_COUNT = 128


def _wrapped_distance(value: float, period: float) -> float:
    """Distance to the nearest multiple of ``period``, wrapping both ways."""
    offset = value % period
    return min(offset, period - offset)


def _ring(distance: float) -> float:
    """Smooth 0..1 profile across one ring."""
    if distance <= RING_CORE:
        return 1.0
    if distance >= RING_FALLOFF:
        return 0.0
    ratio = (distance - RING_CORE) / (RING_FALLOFF - RING_CORE)
    return math.cos(ratio * math.pi / 2.0) ** 2


def _hairline(distance: float) -> float:
    if distance <= 0.6:
        return 1.0
    if distance >= 2.6:
        return 0.0
    return 1.0 - (distance - 0.6) / 2.0


def build_sheet() -> list[list[int]]:
    """Render the neutral-grey ring sheet as a SIZE x SIZE luminance grid."""
    rows: list[list[int]] = []
    for y in range(SIZE):
        centre = y + 0.5
        value = float(BASE)
        value += _ring(_wrapped_distance(centre, RING_PERIOD)) * (RING_PEAK - BASE)
        value += _hairline(
            _wrapped_distance(centre - HAIRLINE_OFFSET, RING_PERIOD)
        ) * (HAIRLINE_PEAK - BASE) * 0.8
        row: list[int] = []
        for x in range(SIZE):
            # Shallow, seamless breathing around the circumference so the ring
            # is not a flat stencil.  Kept well below the threshold where an
            # amplitude change starts to read as a spoke.
            lobe = 1.0 + ANGULAR_DEPTH * math.sin(
                2.0 * math.pi * ANGULAR_LOBES * (x + 0.5) / SIZE)
            row.append(max(0, min(255, int(round(value * lobe)))))
        rows.append(row)
    return rows


def save_tga(rows: list[list[int]], path: Path) -> None:
    """Write an uncompressed 32-bit TGA, bottom-left origin, 8 alpha bits.

    Alpha carries the same luminance so the sheet is still correct if a player
    flips ``Additive`` off in the ini.
    """
    height = len(rows)
    width = len(rows[0])
    header = struct.pack(
        "<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, width, height, 32, 0x08
    )
    payload = bytearray()
    for y in range(height - 1, -1, -1):  # bottom-up
        for value in rows[y]:
            payload += bytes((value, value, value, value))
    path.write_bytes(header + bytes(payload))


def render_preview(rows: list[list[int]], path: Path) -> bool:
    """Draw the con ramp as it lands on the ground, for docs/previews.

    Pillow is a documentation-only dependency; the shipped texture never needs
    it, so a machine without Pillow still regenerates the skin asset.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False

    cell, pad, label_band = 176, 14, 30
    width = pad + len(CON_TIERS) * (cell + pad)
    height = pad + cell + label_band + pad
    canvas = Image.new("RGB", (width, height), (14, 11, 8))
    draw = ImageDraw.Draw(canvas)

    font = ImageFont.load_default(size=13)
    for index, (_key, label, rgb, alpha, scale, _speed, fade_end,
                 _twist) in enumerate(CON_TIERS):
        left = pad + index * (cell + pad)
        centre = cell / 2.0
        # The client fades the ring out from FadeStart to FadeEnd and ramps it
        # in over OpaqueStart..OpaqueEnd; approximate that envelope so the
        # preview shows the real radial falloff rather than a flat donut.
        inner = cell * 0.09
        outer = cell * 0.46 * (fade_end / 22.0)
        opaque = cell * 0.30 * (fade_end / 22.0)
        # Sample the sheet the way the client does: U wraps once around the
        # circumference, and TextureScale decides how many rows of V - and so
        # how many rings - are visible between the center and FadeEnd.
        visible_rows = max(1.0, scale * SIZE)
        tile = Image.new("RGB", (cell, cell), (14, 11, 8))
        pixels = tile.load()
        for y in range(cell):
            for x in range(cell):
                dx, dy = x + 0.5 - centre, y + 0.5 - centre
                radius = math.hypot(dx, dy)
                if radius < inner or radius > outer:
                    continue
                if radius <= opaque:
                    envelope = min(1.0, (radius - inner) / max(1.0, opaque - inner))
                else:
                    envelope = 1.0 - (radius - opaque) / max(1.0, outer - opaque)
                    envelope *= envelope
                angle = (math.atan2(dy, dx) / (2.0 * math.pi)) % 1.0
                sample_v = (radius / outer) * visible_rows
                sample_u = angle * SIZE
                luma = rows[int(sample_v) % SIZE][int(sample_u) % SIZE]
                weight = (luma / 255.0) * envelope * (alpha / 255.0)
                base = pixels[x, y]
                pixels[x, y] = tuple(
                    min(255, int(base[channel] + rgb[channel] * weight))
                    for channel in range(3)
                )
        canvas.paste(tile, (left, pad))
        text_width = draw.textlength(label, font=font)
        draw.text(
            (left + (cell - text_width) / 2.0, pad + cell + 8),
            label, font=font, fill=rgb,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
    return True


def _section(name: str, entries: tuple[tuple[str, object], ...]) -> str:
    body = "".join(f"{key}={value}\n" for key, value in entries)
    return f"[{name}]\n{body}\n"


def _con_section(tier: tuple) -> str:
    key, _label, rgb, alpha, scale, speed, fade_end, twist = tier
    return _section(key, (
        ("Texture", "TargetIndicator"),
        ("TwistFactor", "1.0"),
        ("TwistSpeed", f"{twist:.2f}"),
        ("FrameCount", 0),
        ("Duration", 0),
        ("TextureScale", f"{scale:.3f}"),
        ("TextureSpeed", f"{speed:.4f}"),
        ("ScaleMin", "0.5"),
        ("ScaleMax", "1.5"),
        ("ScaleSpeed", "1.0"),
        ("Alpha", alpha),
        ("Red", rgb[0]),
        ("Green", rgb[1]),
        ("Blue", rgb[2]),
        ("FadeStart", max(2, fade_end - 10)),
        ("FadeEnd", fade_end),
        ("OpaqueStart", "1.0"),
        ("OpaqueEnd", "1.5"),
        ("InitialLength", 1),
        ("GrowSpeed", 1),
        ("FloorOffset", "0.5"),
    ))


# Ground-target reticle and raid markers.  These are not consider rings, so they
# stay on the client's own art; only the two reticle tints move onto the SpinUI
# go/no-go palette.  Marker0..3 are reproduced exactly as the client ships them.
FIXED_SECTIONS = (
    ("Free", "FreeTarget", (96, 214, 132), 240, "0.50", "-0.0010", "0.5"),
    ("FreeInvalid", "FreeTarget", (250, 82, 74), 240, "0.50", "-0.0010", "0.5"),
    ("AssistMarker", "Assist", (248, 214, 140), 150, "0.95", "0.0000", "1.0"),
    ("Marker0", "Mark1", (255, 255, 255), 255, "0.50", "0.0000", "0.9"),
    ("Marker1", "Mark2", (255, 255, 255), 255, "0.50", "0.0000", "0.8"),
    ("Marker2", "Mark3", (255, 255, 255), 255, "0.50", "0.0000", "0.7"),
    ("Marker3", "Mark0", (255, 255, 255), 255, "0.30", "0.0000", "0.6"),
)

INI_INSTRUCTIONS = """[instructions]

Spin's UI Reloaded - the "Vellum & Ember" target ring
----------------------------------------------------

	Generated by tools/generate_target_ring.py together with
	TargetIndicator.tga; edit the CON_TIERS table there and rerun rather than
	hand-patching this file, or the shipped art and the documentation preview
	stop agreeing with what the client draws.

	The client only ever tells the ring which consider tier it is drawing, so
	that tier is where all the meaning has to live.  Colour alone is not enough:
	on a bright beach at noon a yellow ring and a white ring are the same ring.
	Every tier therefore restates its threat four times over -

	  hue          slate > jade > teal > azure > parchment > gold > crimson
	  Alpha        140 (harmless) climbing to 255 (deadly)
	  TextureSpeed 0.0004 (a slow drift) climbing to 0.0026 (pulled inward fast)
	  TextureScale 0.10 (about 1.6 rings) climbing to 0.24 (about 3.8 rings)
	  FadeEnd      16 (a small quiet ring) growing to 22 (the widest ring)

	so a dangerous target reads as dangerous from motion and weight even if you
	cannot separate its colour from the tier below it.

	Deadly is the only tier with a non-zero TwistSpeed, which the client renders
	as a pulse.  If that pulse is too busy for you, set TwistSpeed=0.0 under
	[Deadly]; the rest of the ramp keeps working.

	PointCount is raised from the stock 64 to 128 so the ring reads as a circle
	instead of a polygon when you stand next to your target.

	Everything here reloads live: /indicator off then /indicator on.

Stock format reference
----------------------

	The target indicator is 4 concentric circles textured in such a way that a repeating
	texure is UV animated towards the center. Each con color can have completely different
	settings. It is not a particle effect, it is a specially generated procedural object
	that works independantly of other visual effects and can be toggled on/off in the options
	window. There is a command, /indicator [on|off] which performs the same function.
	When the indicator is turned on, this ini file is reloaded and exiting the game should
	not be required in order to tweak settings or images to your satisfaction.

Section: TargetIndicator

	This section defines properties common to all indicators. The entries have the following purposes:

	* Additive : Set this to 1 to enable additive rendering mode for the ring, 0 for alpha blend.
	* PointCount : This is the number of points that the ring will use to define the circle. There are four
		circles that reprsent the ring, each has their fade level determined by the fade/opaque settings above.

Sections: Trivial, VeryEasy, Easy, FairlyEasy, FairMatch, Difficult, Deadly, Free, FreeInvalid, AssistMarker, Marker0..3

	These sections can be used to configure the target indicator differently for each consider type.
	The entries have the following purpose:

	* Texture : The prefix of the texture to use. ".tga" is appended before opening. If FrameCount is
		above zero, it will format the filenames as "Texture%d.tga" to allow you to load any number of
		frames of animation to use for the indicator. Please note that this is a fairly memory intensive
		way to animate a texture so limiting the number of frames is a good idea. Performance may vary
		dramatically for various cards.
	* FrameCount : How many frames of texture to try to load.
	* Duration : How many milliseconds to show each frame of the animated texture. A value of zero will cause
		a new frame to be selected with each targetting change.
	* TwistFactor : This is a control value that is intended to control how fast each circle of vertices
		in the target indicator rotates on the Z axis relative to each other. Changing this to any value
		besides 1.0 will probably not produce anything worth looking at, but it won't break anything either.
	* TwistSpeed : This value was intended to rotate the entire indicator on the Z-axis but unfortunately
		it does not work as intended at this time. This will get corrected in the future but for now you
		probably want to just leave it at 0.0 unless you want the target indicator to "pulse".
	* TextureScale : How much of the entire texture is visible at one time.
	* TextureSpeed : How fast to move the texture towards the center in texels/msec.
	* ScaleMin : Not used at this time. This and the other two scale values were intended to be used
		to expand the ring when targets are changed, but unfortunately this part was not completed.
	* ScaleMax : Not used.
	* ScaleSpeed : Not used.
	* Alpha : The transparency, combined with any texture alpha values.
	* Red, Green, Blue : Tinting (ie. Vertex color) for the ring.
	* FadeStart : How far from the target does the ring begin to fade out.
	* FadeEnd : The distance of the last visible point on the ring.
	* OpaqueStart : The distance from the target that the ring begins to become visible.
	* OpageEnd : The distance from the targe that the ring is fully visible
	* InitialLength : This is an override on the FadeEnd value, and is intended to be used to make the
		ring quickly expand to full size using the GrowSpeed as the rate of expansion.
	* GrowSpeed : How fast to expand the target ring to full size. A value of 1 will make it instantly appear.
	* FloorOffset : How far off the ground to place the ring.
"""


def build_ini() -> str:
    """Render TargetIndicator.ini from the same table the art comes from."""
    parts = [_section("TargetIndicator", (
        ("Additive", 1),
        ("PointCount", POINT_COUNT),
    ))]
    parts += [_con_section(tier) for tier in CON_TIERS]
    for name, texture, rgb, alpha, scale, speed, floor in FIXED_SECTIONS:
        parts.append(_section(name, (
            ("Texture", texture),
            ("TwistFactor", "1.0"),
            ("TwistSpeed", "0.00"),
            ("FrameCount", 0),
            ("Duration", 0),
            ("TextureScale", scale),
            ("TextureSpeed", speed),
            ("ScaleMin", "0.5"),
            ("ScaleMax", "2.5"),
            ("ScaleSpeed", "1.0"),
            ("Alpha", alpha),
            ("Red", rgb[0]),
            ("Green", rgb[1]),
            ("Blue", rgb[2]),
            ("FadeStart", 10),
            ("FadeEnd", 20),
            ("OpaqueStart", "1.0"),
            ("OpaqueEnd", "1.5"),
            ("InitialLength", 1),
            ("GrowSpeed", 1),
            ("FloorOffset", floor),
        )))
    parts.append(INI_INSTRUCTIONS)
    return "".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-skin", type=Path, default=SKIN,
        help="skin directory to write TargetIndicator.tga into",
    )
    parser.add_argument(
        "--preview", type=Path, default=PREVIEW_DIR / "target_ring.png",
        help="where to render the con-ramp documentation image",
    )
    parser.add_argument(
        "--no-preview", action="store_true",
        help="write only the shipped texture",
    )
    args = parser.parse_args(argv)

    rows = build_sheet()
    target = args.output_skin / "TargetIndicator.tga"
    save_tga(rows, target)
    print(f"wrote {target.relative_to(REPO) if target.is_relative_to(REPO) else target}"
          f"  ({SIZE}x{SIZE} neutral lattice, 32-bit)")
    ini = args.output_skin / "TargetIndicator.ini"
    ini.write_text(build_ini(), encoding="ascii", newline="\n")
    print(f"wrote {ini.relative_to(REPO) if ini.is_relative_to(REPO) else ini}"
          f"  ({len(CON_TIERS)} consider tiers, PointCount {POINT_COUNT})")
    if not args.no_preview:
        if render_preview(rows, args.preview):
            print(f"wrote {args.preview.relative_to(REPO)}  "
                  f"({len(CON_TIERS)} consider tiers)")
        else:
            print("skipped preview: Pillow is not installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
