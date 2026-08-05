#!/usr/bin/env python3
"""Render the complete SpinUI Glass HUD using the real generated atlases."""

from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import render_preview as ui  # noqa: E402
from spinui_glass_theme import FROST, FROST_DIM, texture_tokens  # noqa: E402


def main() -> None:
    tokens = texture_tokens()
    ui.SKIN = REPO / "spinui_glass"
    ui.OUT = REPO / "docs" / "previews"
    ui.OUTPUT_BASENAME = "spinui_glass"
    ui.PREVIEW_SUBTITLE = "SpinUI Glass - midnight frost layout preview"
    ui.TEX.clear()

    # Render helpers read their palette from module globals.  Semantic resource
    # colors (HP, mana, endurance, pet) intentionally retain their originals.
    for name in (
        "BG1", "BG2", "BG3", "CYAN", "EMBER", "GOLD", "GOLD_BRIGHT",
        "LINE", "LINE_SOFT", "TEXT", "TEXT_DIM", "VOID",
    ):
        setattr(ui, name, tokens[name])
    ui.DIM = FROST_DIM
    ui.PARCHMENT = FROST
    ui.main()


if __name__ == "__main__":
    main()
