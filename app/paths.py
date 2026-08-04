"""
app/paths.py — code-adjacent asset paths.

This file resolves assets that ship with the repository (fonts, transitions)
relative to __file__, so they work regardless of the current working directory.

Do not use this for mutable run data (generated runs, character/audio
libraries). Those are deployment-specific and are resolved separately from the
working directory or environment variables.
"""
from __future__ import annotations

from pathlib import Path

# app/paths.py -> app/ -> new_code_v2/
REPO_ROOT = Path(__file__).resolve().parents[1]

ASSET_DIR = REPO_ROOT / "asset"
FONT_DIR = ASSET_DIR / "fonts"
TRANSITIONS_DIR = ASSET_DIR / "transitions"
