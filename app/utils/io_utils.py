"""
app/utils/io_utils.py — durable write primitives.

Helpers for atomically writing text and JSON files.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: str | Path, text: str) -> Path:
    """Write text atomically using a temporary file and os.replace()."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def atomic_write_json(path: str | Path, data, *, indent: int | None = 2) -> Path:
    """Atomically write a JSON file (UTF-8, ensure_ascii=False)."""
    return atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False))
