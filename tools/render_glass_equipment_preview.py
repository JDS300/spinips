#!/usr/bin/env python3
"""Render the Inventory/Equipment window with SpinUI Glass surfaces."""

from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import render_equipment_preview as preview  # noqa: E402
from spinui_glass_theme import FROST_DIM, texture_tokens  # noqa: E402


def main() -> None:
    tokens = texture_tokens()
    preview.SKIN = REPO / "spinui_glass"
    preview.OUT = REPO / "docs" / "previews"
    preview.OUTPUT_FILENAME = "spinui_glass_equipment.png"
    for name in (
        "BG1", "BG2", "CYAN", "EMBER", "GOLD", "GOLD_BRIGHT", "LINE",
        "LINE_SOFT", "TEXT", "TEXT_DIM",
    ):
        setattr(preview, name, tokens[name])
    preview.DIM = FROST_DIM
    preview.main()


if __name__ == "__main__":
    main()
