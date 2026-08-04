"""
app/paths.py — where things live on disk.

Two kinds of path in this project, and they must be resolved differently:

  CODE-ADJACENT ASSETS (this file)
    Fonts, transition overlays. They ship with the repo, are versioned alongside
    the source, and never move relative to it. Resolved from __file__, so they
    work from any working directory — under a process manager, in a container,
    from a cron job, from pytest.

  RUN DATA (main.py: STORAGE_ROOT, CHAR_LIB_ROOT, AUDIO_LIB_ROOT)
    Generated runs and the character/audio libraries. Mutable,
    deployment-specific, and deliberately NOT inside the repo. Those stay
    relative-to-cwd with an environment override, which is correct for data.

Before this existed both kinds resolved against the working directory, so
starting the server from anywhere but the repo root silently dropped transitions
and hard-failed cartoon titles.
"""
from __future__ import annotations

from pathlib import Path

# app/paths.py -> app/ -> new_code_v2/
REPO_ROOT = Path(__file__).resolve().parents[1]

ASSET_DIR = REPO_ROOT / "asset"
FONT_DIR = ASSET_DIR / "fonts"
TRANSITIONS_DIR = ASSET_DIR / "transitions"
