#!/usr/bin/env python3
"""Release gate for the SpinUI target ring and ground decals.

The ring is the only part of the interface that lives in the world rather than
on a window, and its whole job is to answer one question before you pull:
"can this thing kill me?"  That answer is data, not art, so it is checked here.
"""

from __future__ import annotations

from pathlib import Path

from generate_target_ring import (CON_TIERS, DEFAULT_SHEET_STYLE, POINT_COUNT,
                                  SIZE, build_ini, build_sheet, save_tga)

REPO = Path(__file__).resolve().parent.parent
SKIN = REPO / "spinui_reloaded"

# Raid marker art (Mark0..3) is resolved by the client outside this skin folder,
# exactly as the stock skin left it.
CLIENT_RESOLVED_TEXTURES = {"mark0", "mark1", "mark2", "mark3"}


def fail(message: str) -> None:
    raise AssertionError(message)


def parse_indicator_ini(path: Path) -> dict[str, dict[str, str]]:
    """Read one indicator ini, stopping at its free-text [instructions] block."""
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw in path.read_text(encoding="ascii").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1]
            if name == "instructions":
                break
            current = sections.setdefault(name, {})
            continue
        if current is None or "=" not in line:
            fail(f"{path.name}: unparsable line {raw!r}")
        key, _, value = line.partition("=")
        current[key.strip()] = value.strip()
    return sections


def audit_ring_ini() -> dict[str, dict[str, str]]:
    path = SKIN / "TargetIndicator.ini"
    if path.read_text(encoding="ascii") != build_ini():
        fail(
            "spinui_reloaded/TargetIndicator.ini is stale; run "
            "`python tools/generate_target_ring.py`"
        )
    sections = parse_indicator_ini(path)
    header = sections.get("TargetIndicator")
    if header is None:
        fail("TargetIndicator.ini lost its shared [TargetIndicator] header")
    if header.get("Additive") != "1":
        fail("the ring sheet is authored for additive blending")
    if int(header.get("PointCount", "0")) != POINT_COUNT:
        fail(f"ring PointCount must stay {POINT_COUNT} to read as a circle")

    # Threat has to escalate in every channel at once, so a player who cannot
    # separate two hues still gets the message from weight and motion.
    previous = None
    for key, label, rgb, alpha, scale, speed, fade_end, _twist in CON_TIERS:
        section = sections.get(key)
        if section is None:
            fail(f"TargetIndicator.ini is missing the [{key}] consider tier")
        actual = (
            int(section["Red"]), int(section["Green"]), int(section["Blue"]))
        if actual != rgb:
            fail(f"[{key}] tint drifted from the {label} ramp entry: {actual}")
        ladder = (alpha, scale, speed, fade_end)
        if previous is not None and any(
                new <= old for new, old in zip(ladder, previous)):
            fail(
                f"[{key}] does not escalate over the tier below it "
                f"({ladder} vs {previous})"
            )
        previous = ladder
    pulsing = [key for key, *_rest, twist in CON_TIERS if twist]
    if pulsing != ["Deadly"]:
        fail(f"only the Deadly ring may pulse, not {pulsing}")
    return sections


def audit_textures(*section_maps: dict[str, dict[str, str]]) -> int:
    available = {path.name.casefold() for path in SKIN.iterdir()}
    referenced: set[str] = set()
    for sections in section_maps:
        for name, section in sections.items():
            texture = section.get("Texture")
            if texture is None:
                continue
            referenced.add(texture)
            if texture.casefold() in CLIENT_RESOLVED_TEXTURES:
                continue
            if f"{texture}.tga".casefold() not in available:
                fail(f"[{name}] references missing texture {texture}.tga")
    return len(referenced)


# A brightness step this large is a visible edge, and the client will happily
# draw an edge as a spoke if it maps the sheet the way we did not expect.
MAX_NEIGHBOUR_STEP = 40


def audit_ring_sheet() -> None:
    path = SKIN / "TargetIndicator.tga"
    raw = path.read_bytes()
    if len(raw) < 18:
        fail("TargetIndicator.tga is truncated")
    width = int.from_bytes(raw[12:14], "little")
    height = int.from_bytes(raw[14:16], "little")
    depth = raw[16]
    if (width, height, depth) != (SIZE, SIZE, 32):
        fail(f"ring sheet must stay {SIZE}x{SIZE}x32, not {width}x{height}x{depth}")
    body = raw[18:]
    if len(body) != width * height * 4:
        fail("ring sheet payload does not match its header")
    # The shipped sheet is the safe, edge-free style. --style rings and --style
    # flat exist to test the client's mapping and to fall back to vanilla, and
    # neither may reach a release.
    expected = bytearray()
    rows = build_sheet(DEFAULT_SHEET_STYLE)
    for y in range(len(rows) - 1, -1, -1):
        for value in rows[y]:
            expected += bytes((value, value, value, value))
    if bytes(body) != bytes(expected):
        fail(
            "TargetIndicator.tga is not the shipped "
            f"'{DEFAULT_SHEET_STYLE}' sheet; run "
            "`python tools/generate_target_ring.py` with no --style"
        )
    # The client multiplies the sheet by each tier's vertex colour, so any hue
    # baked into the art would poison every tint in the ramp.
    for offset in range(0, len(body), 4 * 97):  # coprime stride, whole sheet
        blue, green, red = body[offset], body[offset + 1], body[offset + 2]
        if not blue == green == red:
            fail("ring sheet must stay neutral grey so the con tints stay true")
    # No hard feature on either axis: this is the invariant that keeps the ring
    # from drawing as streaks when the client maps the sheet the other way.
    for index in range(SIZE):
        column = [rows[y][index] for y in range(SIZE)]
        row = rows[index]
        for series, axis in ((column, "rows"), (row, "columns")):
            for position, value in enumerate(series):
                if abs(value - series[position - 1]) > MAX_NEIGHBOUR_STEP:
                    fail(
                        f"ring sheet has a hard edge along its {axis}; the "
                        f"client can draw that as a spoke"
                    )
                if value <= 0:
                    fail("ring sheet must never fall to black; a gap reads as "
                         "a division between features")


def audit_decal_ini() -> dict[str, dict[str, str]]:
    sections = parse_indicator_ini(SKIN / "DecalIndicator.ini")
    header = sections.get("DecalIndicator")
    if header is None:
        fail("DecalIndicator.ini lost its shared [DecalIndicator] header")
    if int(header.get("PointCount", "0")) != POINT_COUNT:
        fail("ground decals must match the ring's PointCount")
    for name, section in sections.items():
        if section.get("Texture") != "TargetIndicator":
            continue
        # Sections drawing our sheet must use the ring's own density; the stock
        # 0.28 was tuned for a flat noise sheet and reads as a scribble here.
        if section.get("TextureScale") != "0.135":
            fail(f"[{name}] draws the ring sheet at the wrong lattice density")
    return sections


def main() -> int:
    try:
        ring = audit_ring_ini()
        audit_ring_sheet()
        decals = audit_decal_ini()
        textures = audit_textures(ring, decals)
    except AssertionError as exc:
        print(f"Target ring audit: FAIL - {exc}", flush=True)
        return 1
    print("Target ring audit: ALL PASS", flush=True)
    print(
        f"  {len(CON_TIERS)} consider tiers escalate on hue + alpha + speed + "
        f"sweep + radius"
    )
    print(
        f"  sheet {SIZE}x{SIZE} neutral {DEFAULT_SHEET_STYLE}, no hard edge on "
        f"either axis | PointCount {POINT_COUNT} | "
        f"{textures} indicator textures resolved"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
