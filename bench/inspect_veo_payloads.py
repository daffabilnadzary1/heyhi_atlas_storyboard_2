"""
Later can erase this file, this is only used to inspect the prompt handed to Veo before budget approval

bench/inspect_veo_payloads.py — show EXACTLY what would be sent to Veo for each
scene type, WITHOUT calling Veo (no network, no credits, no budget needed).

For every scene it prints: task/model routing, reference_from, aspect_ratio,
duration, safety, the full prompt, and what image/reference
bytes get attached (as sizes, not raw bytes).

Usage:
  # built-in representative sample scenes (creates its own dummy assets)
  python -m bench.inspect_veo_payloads

  # a real run's blueprint.json + on-disk assets
  python -m bench.inspect_veo_payloads --run _storage/atlas_storyboard/run_0X

NOTE: the prompt shown is the FINAL composed prompt (claude.md §4.2). For
video-with-audio scenes it appends 'Audio sync: The character says "<text>"'
so Veo voices the exact words — the native audio L6 diarizes for TTS timing.
The blueprint's own prompt field stays dialogue-free (director AI RULE #5);
the spoken text is appended here at submit time. B-Roll prompts are unchanged.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from app.pipeline.scene_gen import SceneGenerator, route
from app.clients.video_veo_client import VeoError


def _fake_mp4(path: Path, seconds: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=duration={seconds}:size=160x120:rate=10", str(path)],
        check=True,
    )


# These fixtures cover the four routing cases, so the no-arg mode demonstrates the
# whole grammar without needing a real run:
#   s1  storyboard: -> reference-to-video / Fast   (first speaking scene of a topic)
#   s2  scene:      -> image-to-video     / Lite   (continuation, seeds from s1)
#   b1  background: -> image-to-video     / Lite   (opening B-Roll)
#   b2  scene:      -> image-to-video     / Lite   (closing B-Roll, holds s2's frame)
# Keep them in sync with director.ROUTE_BY_PREFIX — b1 previously read
# "keyframe:kf1", a prefix that was removed from the grammar, and route() raised
# on it every time this ran with no --run.
SAMPLE_SCENES = [
    {
        "id": "s1", "type": "video-with-audio", "topic": "intro",
        "task": "reference-to-video", "model": "Veo 3.1 Fast",
        "reference_from": "storyboard:sb1", "aspect_ratio": "16:9", "length": None,
        "text": "Welcome to onboarding.",
        "prompt": ("Cinematography: medium shot, 50mm, Subject: a presenter facing "
                   "camera, Action: the character's lips and jaw move continuously as "
                   "if speaking..., Context: office, Style and Ambience: warm; wordless "
                   "illustration..., Ambient noise: faint room tone, Language: English"),
    },
    {
        "id": "s2", "type": "video-with-audio", "topic": "intro",
        "task": "image-to-video", "model": "Veo 3.1 Lite",
        "reference_from": "scene:s1", "aspect_ratio": "16:9", "length": None,
        "text": "Let us begin.",
        "prompt": ("Cinematography: consistent with previous frame, Subject: same "
                   "presenter, Action: lips and jaw continue moving..., Context: same, "
                   "Style and Ambience: consistent with previous frame; wordless "
                   "illustration..., Ambient noise: room tone, Language: English"),
    },
    {
        "id": "b1", "type": "B-Roll", "broll_role": "opening",
        "task": "image-to-video", "model": "Veo 3.1 Lite",
        "reference_from": "background:bg1", "aspect_ratio": "16:9", "length": 2,
        "text": "",
        "prompt": ("Cinematography: slow push-in, Subject: an empty desk with a laptop, "
                   "Action: gentle light shift, Context: office at dawn, Style and "
                   "Ambience: calm; wordless illustration..., Ambient noise: quiet hum, "
                   "Language: English"),
    },
    {
        "id": "b2", "type": "B-Roll", "broll_role": "closing",
        "task": "image-to-video", "model": "Veo 3.1 Lite",
        "reference_from": "scene:s2", "aspect_ratio": "16:9", "length": 2,
        "text": "",
        "prompt": ("Cinematography: hold, Subject: presenter at rest, Action: a calm "
                   "breath, Context: same office, Style and Ambience: consistent with "
                   "previous frame; wordless illustration..., Ambient noise: room tone, "
                   "Language: English"),
    },
]


def _print_spec(gen: SceneGenerator, scene: dict) -> None:
    from app.pipeline.scene_gen import compose_veo_prompt, veo_generation_seconds
    from app.clients.video_veo_client import GeminiVeoClient

    sid = scene.get("id", "?")
    stype = scene.get("type")
    print("=" * 78)
    print(f"SCENE {sid}  |  type={stype}  broll_role={scene.get('broll_role')}")
    try:
        task, model = route(scene)
        print(f"  route         : task={task}   model={model}")
    except Exception as e:
        print(f"  route         : ERROR {e}")
    print(f"  reference_from: {scene.get('reference_from')}")
    print(f"  aspect_ratio  : {scene.get('aspect_ratio', '16:9')}")

    # duration: what Veo is asked to generate vs how the clip is trimmed after
    gen_s = veo_generation_seconds(scene)
    print(f"  Veo gen length: {gen_s}s   (sent to Veo as duration_seconds)")
    if stype == "B-Roll":
        print(f"  blueprint len : {scene.get('length')}s   -> clip TRIMMED to this after generation")
        print(f"  generate_audio: False   (Veo emits no audio for B-Roll)")
    else:
        print(f"  trim          : by L6 to last TTS end")
        print(f"  generate_audio: True    (Veo voices the words for diarization)")

    safety = scene.get("safety", "Allow (Adult only)")
    pg = GeminiVeoClient._PERSON_GENERATION.get(safety, "allow_adult")
    print(f"  safety        : {safety}  -> person_generation={pg}")

    
    # attached input FILES (independent of prompt; may be absent pre-asset-gen)
    try:
        image_path, ref_paths = gen._resolve_input_paths(scene)
        if image_path:
            print(f"  image seed    : {image_path}   (image-to-video)")
        if ref_paths:
            print(f"  reference img : {[str(p) for p in ref_paths]}   (reference-to-video, attached to Veo)")
        if not image_path and not ref_paths:
            print("  input files   : none")
    except VeoError as e:
        print(f"  input files   : NOT ON DISK YET ({e})")

    # spoken text is part of the FINAL prompt for video-with-audio (§4.2)
    if stype == "video-with-audio":
        print(f'  spoken text   : "{(scene.get("text") or "").strip()}"  (appended to prompt below)')

    # composed prompt — needs no assets, always shown
    print("  FINAL PROMPT sent to Veo:")
    print(f"      {compose_veo_prompt(scene)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Inspect Veo payloads (no network)")
    ap.add_argument("--run", type=Path, help="a run dir with blueprint.json + assets")
    a = ap.parse_args(argv)

    if a.run:
        run = a.run
        scenes = json.loads((run / "blueprint.json").read_text())["scenes"]
        gen = SceneGenerator(run, client=None)     # client unused for build_spec
        print(f"# Inspecting real run: {run}  ({len(scenes)} scenes)\n")
    else:
        run = Path(tempfile.mkdtemp())
        # dummy assets so every sample scene resolves its input the way a real run
        # would — otherwise the payload print says "NOT ON DISK YET" and shows
        # nothing about what actually gets attached.
        (run / "storyboard").mkdir(parents=True); (run / "storyboard/sb1.png").write_bytes(b"\x89PNG-sb")
        (run / "backgrounds").mkdir(parents=True); (run / "backgrounds/bg1.png").write_bytes(b"\x89PNG-bg")
        _fake_mp4(run / "scenes/s1.mp4"); _fake_mp4(run / "scenes/s2.mp4")   # for scene-chain seeds
        scenes = SAMPLE_SCENES
        gen = SceneGenerator(run, client=None)
        print("# Inspecting built-in sample scenes (dummy assets)\n")

    for sc in scenes:
        _print_spec(gen, sc)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())