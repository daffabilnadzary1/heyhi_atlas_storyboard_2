"""
app/pipeline/image_gen.py — Layer 4 asset generation (Gemini 2.5 Flash Image).

Generates backgrounds and storyboards from the resolved blueprint.
Characters come from the shared character library and are never generated here.

The blueprint style is prepended to every prompt at generation time.

Assets are generated in dependency order:
1. Backgrounds
2. Storyboards (which reference backgrounds and character PNGs)

Reference resolution:
- Background -> run/backgrounds/<id>.png
- Character  -> character_library/<id>.png
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from app.utils.retry import RetriesExhausted, retry_call
from app.utils.retry import backoff_from_env as _backoff_from_env

# Default retry backoff; overridable at the composition roots (API endpoint /
# CLI) via ATLAS_IMAGE_BACKOFF. 
DEFAULT_RETRY_BACKOFF_S = 2.0


def backoff_from_env() -> float:
    """Entry-point helper: resolve retry backoff from env, else the default."""
    return _backoff_from_env("ATLAS_IMAGE_BACKOFF", DEFAULT_RETRY_BACKOFF_S)


# ---------------------------------------------------------------- client seam
class ImageLLM(Protocol):
    """references = attached reference-image PNG bytes. Returns PNG bytes."""
    def generate(self, prompt: str, references: list[bytes]) -> bytes: ...


class AssetError(RuntimeError):
    pass


def _compose_prompt(style: str, prompt: str) -> str:
    """Prepend the blueprint style to an image prompt."""
    s = (style or "").strip().rstrip(",").strip()
    return f"{s}, {prompt}" if s else prompt


# ---------------------------------------------------------------- dispatcher
class AssetGenerator:
    def __init__(
        self,
        run_dir: str | Path,
        char_lib_root: str | Path,
        client: ImageLLM,
        max_retries: int = 2,
        retry_backoff_s: float = DEFAULT_RETRY_BACKOFF_S,
        resume: bool = False,
    ):
        self.run = Path(run_dir)                # Save the location of the run
        self.char_lib = Path(char_lib_root)     # Save the location of the character library
        self.client = client
        self.max_retries = max_retries
        self.backoff = retry_backoff_s
        # resume=True: an entry whose PNG is already on disk is left alone and not
        # regenerated. This is what makes a half-finished /pipeline/assets cheap to
        # retry — see reused_count and the note on generate_all.
        self.resume = resume
        self.reused: list[Path] = []            # files skipped because they existed
        self.bg_dir = self.run / "backgrounds"  # Directory to save generate background
        self.sb_dir = self.run / "storyboard"   # Directory to save generate storyboards

    # Converts JSON into python dictionary
    def _load_blueprint(self) -> dict:
        bp_path = self.run / "blueprint.json"
        if not bp_path.is_file():
            raise AssetError(f"blueprint.json not found in {self.run}")
        return json.loads(bp_path.read_text(encoding="utf-8"))

    # Given an ID, where is the file located (background/character)
    def _resolve_ref(self, ref_id: str, bg_ids: set[str]) -> Path:
        # bg ids are run-local generated plates; everything else is a library char
        p = (self.bg_dir / f"{ref_id}.png") if ref_id in bg_ids else (self.char_lib / f"{ref_id}.png")
        if not p.is_file():
            raise AssetError(f"reference '{ref_id}' resolves to missing file {p}")
        return p

    def _already_done(self, dest: Path) -> bool:
        """Return True if resume mode can reuse an existing asset."""
        if self.resume and dest.is_file():
            self.reused.append(dest)
            return True
        return False

    def _gen(self, prompt: str, ref_paths: list[Path], dest: Path) -> Path:
        """One image with retry + exponential backoff."""
        refs = [p.read_bytes() for p in ref_paths]

        def once() -> Path:
            png = self.client.generate(prompt, refs)         # Calls the gemini model
            if not png:
                raise AssetError("empty image bytes")
            dest.parent.mkdir(parents=True, exist_ok=True)   # Create the directory
            dest.write_bytes(png)                            # Place the generated file
            return dest

        try:
            path, attempts = retry_call(
                once, attempts=self.max_retries + 1, exc_type=Exception,
                backoff_s=self.backoff)
            # Cost is recorded per SUCCESSFUL image. Failed attempts before it
            # are noted via `attempts` but not billed separately — a call that
            # errored produced no image, and Gemini bills image output. If that
            # assumption turns out wrong, this is the line to change.
            from app.costs import record, record_tokens
            record(self.run, layer="L4", provider="gemini",
                   model=getattr(self.client, "model", "gemini-2.5-flash-image"),
                   unit="image", quantity=1, measured=True,
                   asset=dest.name, attempts=attempts)
            usage = getattr(self.client, "usage_log", None)
            if usage:
                record_tokens(self.run, layer="L4",
                              model=getattr(self.client, "model", "gemini-2.5-flash-image"),
                              usage=usage[-1], asset=dest.name, priced=False)
            return path
        except RetriesExhausted as ex:
            raise AssetError(
                f"gen failed for {dest.name} after {self.max_retries + 1} attempts: {ex.last}"
            )

    # ---- backgrounds (no references, empty environment plates) ----
    def generate_backgrounds(self, bp: dict) -> list[Path]:
        style = bp.get("style", "")
        out: list[Path] = []
        for bg in bp.get("backgrounds", []):
            dest = self.bg_dir / f"{bg['id']}.png"
            if self._already_done(dest):
                out.append(dest)
                continue
            out.append(self._gen(_compose_prompt(style, bg["prompt"]), [], dest))
        return out

    # ---- storyboards (resolve library chars + generated bgs -> 2x2 grid) ----
    def generate_storyboards(self, bp: dict) -> list[Path]:
        style = bp.get("style", "")
        bg_ids = {b["id"] for b in bp.get("backgrounds", [])}
        out: list[Path] = []
        for sb in bp.get("storyboard", []):
            dest = self.sb_dir / f"{sb['id']}.png"
            if self._already_done(dest):
                out.append(dest)
                continue
            refs = [self._resolve_ref(r, bg_ids) for r in sb.get("reference", [])]
            out.append(self._gen(_compose_prompt(style, sb["prompt"]), refs, dest))
        return out

    def generate_all(self, bp: dict | None = None) -> dict[str, list[Path]]:
        """Generate all assets in dependency order.

        Backgrounds are generated first because storyboards reference them.

        Returns:
            {"backgrounds": [...], "storyboard": [...]}

        With resume=True, existing PNGs are reused instead of regenerated.
        Raises AssetError if generation or reference resolution fails.
        """
        bp = bp if bp is not None else self._load_blueprint()
        backgrounds = self.generate_backgrounds(bp)     # FIRST — referenced below
        storyboards = self.generate_storyboards(bp)
        return {"backgrounds": backgrounds, "storyboard": storyboards}


# ---------------------------------------------------------------- Gemini client
class GeminiImageClient:
    """ImageLLM implementation backed by Gemini 2.5 Flash Image."""

    def __init__(self, client, model: str = "gemini-2.5-flash-image",
                 aspect_ratio: str = "16:9"):
        self.client = client
        self.model = model
        self.aspect_ratio = aspect_ratio
        # One entry per successful generate(), in order — same side-channel
        # pattern as GeminiDirector.usage_log, and for the same reason: the
        # ImageLLM Protocol is `generate(str, list[bytes]) -> bytes`, and
        # billing does not belong in that contract. AssetGenerator drains this
        # after generate_all(). Retries append too, since each attempt bills.
        self.usage_log: list[dict] = []

    def generate(self, prompt: str, references: list[bytes]) -> bytes:
        from google.genai import types
        contents: list = [prompt]
        for data in references:
            contents.append(types.Part.from_bytes(data=data, mime_type="image/png"))
        # Actual call to GEMINI API
        resp = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],                    # Ensure that Gemini returns an image
                image_config=types.ImageConfig(aspect_ratio=self.aspect_ratio),
            ),
        )
        # Find the image response
        for part in resp.candidates[0].content.parts:
            inline = getattr(part, "inline_data", None)
            if inline is not None and inline.data:
                from app.costs import usage_from_response
                # Recorded for information only — images are priced per image,
                # not per token (see PRICING in app/costs.py for why).
                self.usage_log.append(usage_from_response(resp))
                return inline.data
        raise RuntimeError("Gemini returned no image part")


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="L4 asset generation (Gemini 2.5 Flash Image)")
    ap.add_argument("--run", type=Path, required=True, help="run directory (holds blueprint.json)")
    ap.add_argument("--char-lib", type=Path, default=Path("_storage/character_library"))
    ap.add_argument("--aspect-ratio", default="16:9", help="image plate aspect ratio (must match the video)")
    a = ap.parse_args(argv)

    from app.config import make_client
    gen = AssetGenerator(
        a.run, a.char_lib, GeminiImageClient(make_client(), aspect_ratio=a.aspect_ratio),
        retry_backoff_s=backoff_from_env(),
    )
    result = gen.generate_all()
    for kind, paths in result.items():
        print(f"{kind}: {len(paths)} -> {[p.name for p in paths]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())