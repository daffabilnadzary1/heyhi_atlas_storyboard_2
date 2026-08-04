"""
app/libraries.py — Layer 3 library indexes (characters + audio).

Two on-disk libraries, each = a folder of assets + an index.json:

  _storage/character_library/   *.png  + index.json
  _storage/audio_library/       *.wav  + index.json

These index schemas are the READ contract for the L3 API (D2T4:
GET /pipeline/characters, GET /pipeline/audios) and the selection
validator (D2T5). image_path / sample_path are stored RELATIVE to the
library root, so the tree can move (local -> S3) without rewrites.

CLI:
  # D2T1 — scan PNGs, scaffold/merge index.json, validate
  python -m app.libraries characters --root _storage/character_library
  # D2T3 — validate the authored audio index.json (--strict-files to require wavs)
  python -m app.libraries audios --root _storage/audio_library
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")                               # validates a snake_case id
_LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-[A-Z]{2})?$")   # Ensure language codes (BCP-47 style)


class CharacterEntry(BaseModel):
    char_id: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)     # e.g. ["adult","female","teacher"]
    image_path: str                                   # relative to character_library/


class AudioEntry(BaseModel):
    audio_id: str
    voice_name: str                                   # Azure short name, e.g. en-US-JennyNeural
    voice_id_elevenlabs: str | None = None            # ElevenLabs voice ID; None = Azure-only
    language: str                                     # BCP-47 locale, e.g. en-US
    sample_path: str                                  # relative to audio_library/


# ---------------------------------------------------------------- load
# Helper function to load character and audio JSON into objects
def _load(root: Path, model):
    data = json.loads((root / "index.json").read_text(encoding="utf-8"))
    return [model.model_validate(e) for e in data]


def load_character_index(root: Path) -> list[CharacterEntry]:
    return _load(root, CharacterEntry)


def load_audio_index(root: Path) -> list[AudioEntry]:
    return _load(root, AudioEntry)

# Function to write python objects as JSON
def _write_index(root: Path, entries) -> None:
    (root / "index.json").write_text(
        json.dumps([e.model_dump() for e in entries], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------- build (characters)
# Scans for png images --> Creates/ update the index.json (If update, still preserve old one)
def build_character_index(
    root: Path, exts: tuple[str, ...] = (".png",)
) -> tuple[list[CharacterEntry], list[str]]:
    """Scan the library folder, scaffold entries, MERGE over any existing
    index.json (never clobbers human-authored description/tags). Idempotent."""
    root = root.resolve()
    prior: dict[str, CharacterEntry] = {} # Load the previous metadata JSON, so when we rebuild, we don't lose it
    if (root / "index.json").exists():
        prior = {e.char_id: e for e in load_character_index(root)}

    imgs = sorted(p for p in root.iterdir() if p.suffix.lower() in exts) # save all the *.png into imgs variable
    disk_ids = {p.stem for p in imgs}
    # For every png, make JSON code
    entries = [
        CharacterEntry(
            char_id=p.stem,
            description=prior[p.stem].description if p.stem in prior else "",
            tags=prior[p.stem].tags if p.stem in prior else [],
            image_path=p.name,
        )
        for p in imgs
    ]
    warnings = [
        f"index lists '{cid}' but no matching {exts} file on disk"
        for cid in prior
        if cid not in disk_ids
    ]
    return entries, warnings

# ---------------------------------------------------------------- build (audio)
# Scans for wav and update the JSON automatically
def build_audio_index(
    root: Path, exts: tuple[str, ...] = (".wav",)
) -> tuple[list[AudioEntry], list[str]]:
    """UNION merge, keyed by sample filename. Unlike characters, audio
    metadata (voice_name/language) is NOT derivable from the file, so:
      * authored entries are kept even if their wav isn't generated yet
        (warned) — this is why we never scan-and-replace,
      * wavs with no metadata get a stub (audio_id = stem) to fill in.
    Idempotent; safe before and after sample generation."""
    root = root.resolve()
    prior: dict[str, AudioEntry] = {}
    if (root / "index.json").exists():
        prior = {e.sample_path: e for e in load_audio_index(root)}
 
    disk = {p.name for p in root.iterdir() if p.suffix.lower() in exts}
    entries: list[AudioEntry] = []
    warnings: list[str] = []
 
    for name in sorted(prior.keys() | disk):
        if name in prior:
            entries.append(prior[name])
            if name not in disk:
                warnings.append(f"'{name}': in index but wav not generated yet (run D2T2)")
        else:  # wav on disk, no metadata -> stub for the human to complete
            entries.append(AudioEntry(
                audio_id=Path(name).stem, voice_name="", language="", sample_path=name,
            ))
            warnings.append(f"'{name}': wav has no metadata — stub added, fill voice_name/language")
    return entries, warnings


# ---------------------------------------------------------------- validate
def validate_character_index(root: Path) -> list[str]:
    probs: list[str] = []
    seen: set[str] = set()
    for e in load_character_index(root):
        if not _ID_RE.match(e.char_id):
            probs.append(f"char_id '{e.char_id}' is not snake_case")
        if e.char_id in seen:
            probs.append(f"duplicate char_id '{e.char_id}'")
        seen.add(e.char_id)
        if not (root / e.image_path).is_file():
            probs.append(f"{e.char_id}: image_path '{e.image_path}' does not resolve")
    return probs


def validate_audio_index(root: Path, strict_files: bool = False) -> list[str]:
    probs: list[str] = []
    seen: set[str] = set()
    for e in load_audio_index(root):
        if not _ID_RE.match(e.audio_id):
            probs.append(f"audio_id '{e.audio_id}' is not snake_case")
        if e.audio_id in seen:
            probs.append(f"duplicate audio_id '{e.audio_id}'")
        seen.add(e.audio_id)
        if not _LOCALE_RE.match(e.language):
            probs.append(f"{e.audio_id}: language '{e.language}' is not a valid BCP-47/ISO-639 locale")
        if strict_files and not (root / e.sample_path).is_file():
            probs.append(f"{e.audio_id}: sample_path '{e.sample_path}' does not resolve")
    return probs


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Build/validate L3 library indexes")
    ap.add_argument("kind", choices=["characters", "audios"])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--strict-files", action="store_true",
                    help="audios: require every sample wav to exist")
    a = ap.parse_args(argv)

    if a.kind == "characters":
        entries, warns = build_character_index(a.root)
        _write_index(a.root, entries)
        probs = validate_character_index(a.root)
        empties = [e.char_id for e in entries if not e.description.strip()]
        print(f"characters: {len(entries)} entries -> {a.root/'index.json'}")
        for w in warns:
            print("  warn:", w)
        if empties:
            print("  warn: empty description (fill before Gate 1):", empties)
    else:
        entries, warns = build_audio_index(a.root)
        _write_index(a.root, entries)
        probs = validate_audio_index(a.root, strict_files=a.strict_files)
        n = len(load_audio_index(a.root))
        print(f"audios: {n} entries validated at {a.root/'index.json'}")
        for w in warns:
            print("  warn:", w)

    print("VALID" if not probs else "PROBLEMS:\n  - " + "\n  - ".join(probs))
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())