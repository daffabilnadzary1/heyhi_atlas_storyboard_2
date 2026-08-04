"""
app/schemas.py — Layer 1 (Source + Config) I/O schemas.

ConfigIn is the user-facing config subset (language/audience/depth/style/
objective + aspect_ratio). characters/audios are NOT here — they are chosen
later in Layer 3 (/pipeline/select) after blueprint approval. ConfigIn maps
1:1 onto director.DirectorConfig at direct() time.

This file holds BOTH halves of the contract, which is worth knowing when you
change something:

  * The blueprint models (BackgroundRef, Storyboard, Scene, VideoBlueprint) —
    "schema v3". These describe blueprint.json, i.e. the artifact every layer
    from L3 onwards reads. Editing one of these changes what the director is
    allowed to emit AND what already-written blueprints on disk validate
    against; old runs in _storage are NOT migrated.
  * The HTTP request/response models (ConfigIn/Out, DirectIn/Out, ...) — the
    API surface main.py exposes. Purely per-request, safe to change freely.

The pydantic models only check SHAPE. Every cross-field rule that actually
matters (character_count matches the scenes, reference_from points at something
real, B-Roll carries no characters, word budget) lives in
director.validate_blueprint, and the resolved-blueprint subset is re-checked in
patch_blueprint._check_resolved. A blueprint can satisfy this file and still be
rejected there.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

class BackgroundRef(BaseModel):
    id: str = Field(..., description="short unique background id, e.g. 'bg_office_day'")
    prompt: str = Field(
        ...,
        description=(
            "narrative image-gen prompt for the empty environment plate "
            "(no characters). Wide establishing shot."
        ),
    )


class Storyboard(BaseModel):
    # REMOVED 2026-08-03: `model` (defaulted to "gemini-2.5-flash-image"). It was
    # never read — GeminiImageClient hard-codes its own model — so it looked like
    # a per-storyboard setting that did nothing. Blueprints on disk still carry
    # it; pydantic drops unknown keys, so old runs parse unchanged.
    id: str = Field(..., description="short unique storyboard id, e.g. 'sb_1'")
    prompt: str = Field(
        ...,
        description=(
            "2x2 multipanel storyboard prompt with per-panel timecodes "
            "[00:00-00:02] .. [00:06-00:08]"
        ),
    )
    reference: list[str] = Field(
        default_factory=list,
        description=(
            "placeholder char_ids (from scene.characters) + bg_ids used to "
            "compose this keyframe. char_ids are opaque tokens the user "
            "resolves to real library characters."
        ),
    )

class AudioMapping(BaseModel):
    """One character's voice for one scene.

    The same char_id must carry the same audio_id in EVERY scene it appears in —
    otherwise a character's voice changes mid-video. That invariant is checked
    twice: on the director's output (validate_blueprint) and again after the
    user's selection is applied (patch_blueprint._check_resolved).
    """
    char_id: str = Field(..., description="placeholder char_id from scene.characters")
    audio_id: str = Field(
        ...,
        description="placeholder audio id the user resolves to a library voice",
    )

# For the front-end voice contract
class VoiceEntry(BaseModel):
    voice_id: str
    name: str
    preview_url: str | None = None
    languages: list[str] = Field(default_factory=list)  # verified_languages[].language, else labels.language, else ["unknown"]
    gender: str = "unknown"                              # labels.gender, else "unknown"


# ---------------------------------------------------------------- vocabularies
# These Literals are the pipeline's closed vocabularies. Adding a value here is
# never enough on its own — each one has downstream code keyed on it. The
# comments below name what else has to change.

SceneType = Literal["B-Roll", "video-with-audio"]

# Only two roles exist in code.
BRollRole = Literal["opening", "closing"]

Depth = Literal["standard", "deep dive"]

# style_type is DERIVED, not user-supplied: director.derive_style_type keyword-
# matches the free-text `style` string into one of these. Its only consumer today
# is renderer.title_style_for (cartoon gets a different title treatment).
StyleType = Literal["realism", "cartoon", "semi-realism"]

# Add objective literal (popular use cases)
AspectRatio = Literal["16:9", "9:16"]

# task and model are not independent — the reference_from prefix determines both
# (director.ROUTE_BY_PREFIX). storyboard: -> reference-to-video + Fast;
# background:/scene: -> image-to-video + Lite. scene_gen.route() re-checks the
# pairing at generation time, right before the billable call.
VeoTask = Literal["image-to-video", "reference-to-video"]
VeoModel = Literal["Veo 3.1 Fast", "Veo 3.1 Lite"]

# Selects the blueprint SHAPE rules, read from config.json by
# director.read_blueprint_type. Today the only behavioural difference is the
# opening section: "opening" forces the first B-Roll to 4s and burns the title
# card over it; "summary" keeps the director's short plate with no title.
# TODO: change3_short_animation.md specs a third value, "illustration", with its
# own director. It is NOT implemented — adding it here would let it through
# validation and then fail further down.
BlueprintType = Literal["opening", "summary"]

class Scene(BaseModel):
    """One Veo clip. The scenes list IS the video timeline — they are concatenated
    in list order with no cuts (renderer.merge_scenes).

    `id` doubles as a filename in three places, so it must be filesystem-safe:
        veo_raw/<id>.mp4     pristine Veo output
        scenes/<id>.mp4      after L6 trims + muxes the voice track
        tts/<id>_*.wav       the voice clips and the timings sidecar
    """
    id: str = Field(..., description="short unique scene id, e.g. 's1'")
    task: VeoTask = Field(
        ...,
        description=(
            "'reference-to-video' when reference_from is 'storyboard:...', "
            "'image-to-video' when reference_from is a "
            "prior scene id. Enforced by validator."
        ),
    )
    model: VeoModel = Field(
        ...,
        description=(
            "'Veo 3.1 Fast' pairs with reference-to-video. 'Veo 3.1 Lite' "
            "pairs with image-to-video."
        ),
    )
    # "in config.language" is load-bearing, not decoration. With use_schema on,
    # these descriptions travel to Gemini as JSON-schema annotations, and on
    # run_77d71eba the only field that came back in the requested language was
    # `title` — the only one whose description named the language. See
    # docs/open-questions.md #28.
    text: str = Field(
        "",
        description=(
            "spoken narration for this scene, written in config.language "
            "(empty for B-Roll). This is what the viewer HEARS and reads as "
            "subtitles — unlike `prompt`, which stays in English because it "
            "instructs Veo."
        ),
    )
    # KNOWN GAP: patch_blueprint rewrites placeholder char_ids in `characters`,
    # `audios` and storyboard references — but NOT inside this prompt string. If
    # the director writes a placeholder id into the prompt text (it sometimes
    # does, e.g. "a medium shot of char_narrator"), that raw token is what Veo
    # receives. See docs/open-questions.md.
    prompt: str = Field(
        ...,
        description=(
            "Structured Veo prompt. MUST contain the labels: Cinematography, "
            "Subject, Action, Context, Style and Ambience, Ambient noise. "
            "Language emitted but not validator-enforced. Negative prompt "
            "intentionally omitted per AI RULE #1."
        ),
    )
    safety: str = Field("Allow (Adult only)")
    reference_from: str = Field(
        ...,
        description=(
            "one of: 'storyboard:<sb_id>', "
            "'scene:<earlier_scene_id>', or bare '<earlier_scene_id>'"
        ),
    )
    type: SceneType
    broll_role: BRollRole | None = None
    length: float | None = Field(
        None,
        description="seconds; REQUIRED for B-Roll, null for video-with-audio",
    )
    aspect_ratio: AspectRatio = "16:9"
    topic: str | None = Field(
        None,
        description="short topic label — REQUIRED for video-with-audio",
    )
    characters: list[str] = Field(
        default_factory=list,
        description=(
            "placeholder char_ids present in this scene (e.g. "
            "['char_teacher', 'char_student']). Semantic role-based ids."
        ),
    )
    audios: list[AudioMapping] = Field(
        default_factory=list,
        description=(
            "voice mapping for each char_id in this scene. Every char_id in "
            "'characters' MUST have a corresponding entry."
        ),
    )


class VideoBlueprint(BaseModel):
    """blueprint.json — schema v3. The one artifact the whole pipeline agrees on.

    Written twice per run, both times atomically:
      1. /pipeline/direct writes the director's output (placeholder char_ids).
      2. /pipeline/select snapshots that to blueprint.placeholder.json and
         rewrites blueprint.json with the user's real library ids.
    Everything downstream reads the resolved version.

    Note there is no `keyframe` field. Older blueprints in _storage still carry
    one; it was removed from the schema and pydantic drops unknown keys on the
    way in, so any `keyframe` you see on disk is legacy and unread.
    """
    title: str = Field(..., min_length=1, max_length=80,
                       description="short on-screen video title, in config.language")
    style: str
    style_type: StyleType = "realism"
    character_count: int = Field(
        ...,
        ge=0,
        description=(
            "distinct character count. Must equal the number of unique "
            "char_ids appearing across all scenes."
        ),
    )
    music_style: str = Field(
        ...,
        description=(
            "one-line description of the video's music track (genre + mood + "
            "instrumentation). Consumed by the music generation layer."
        ),
    )
    backgrounds: list[BackgroundRef]
    scenes: list[Scene]
    storyboard: list[Storyboard]

class ConfigIn(BaseModel):
    # extra="forbid": unknown/typo'd fields -> 422 instead of silent drop
    model_config = ConfigDict(extra="forbid")
    blueprint_type: BlueprintType = "opening"
    language: str = Field(..., min_length=1)
    audience: str = Field(..., min_length=1)
    depth: Depth = "standard"
    style: str = Field(..., min_length=1)
    objective: str = Field(..., min_length=1)

    # LOCKED TO 16:9 (decision 2026-08-01). The type is Literal["16:9"] here, not
    # AspectRatio, so a request asking for "9:16" is a 422 rather than a run that
    # silently produces something broken.
    #
    # Why locked: portrait does not work end to end today. main._image_client()
    # builds GeminiImageClient with its default 16:9 and never reads this field,
    # so a 9:16 run generates LANDSCAPE backgrounds and storyboards and then asks
    # Veo for portrait video. On top of that, all five bundled transition overlays
    # are 1920x1080 and apply_transitions scales them to the video geometry
    # without honouring TransitionEntry.aspect_ratio, so they would stretch.
    #
    # The lock is deliberately ONLY here. Scene.aspect_ratio, the AspectRatio
    # literal, the DIRECTOR_RULES interpolation and the Veo plumbing all still
    # carry both values, so unlocking is this line plus passing the config
    # through in _image_client — not a re-implementation. See
    # docs/open-questions.md #13.
    aspect_ratio: Literal["16:9"] = "16:9"


class ConfigOut(BaseModel):
    run_id: str
    config_path: str


class UploadOut(BaseModel):
    run_id: str
    source_path: str
    bytes: int

class DirectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    force: bool = False                               # overwrite an existing blueprint, for regeneration purposes
    max_retries: int = Field(2, ge=0, le=5)
    # Hand VideoBlueprint to Gemini as a response_schema so the reply cannot be
    # malformed JSON or carry an out-of-vocabulary enum. ON by default since
    # 2026-08-02. It does NOT remove retries caused by validate_blueprint's
    # semantic rules — those are the common ones. See docs/open-questions.md #25.
    use_schema: bool = True
 
class DirectOut(BaseModel):
    run_id: str
    blueprint_path: str
    character_count: int
    scenes: int
    regenerated: bool

class SelectionItem(BaseModel):
    # extra="forbid": typo'd keys -> 422
    model_config = ConfigDict(extra="forbid")
    placeholder_id: str = Field(..., min_length=1)   # blueprint scene.characters id, e.g. 'char_1'
    char_id: str = Field(..., min_length=1)          # id in character_library/index.json
    audio_id: str = Field(..., min_length=1)         # id in audio_library/index.json
 
 
class SelectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    voice_source: Literal["index", "elevenlabs"] = "elevenlabs"
    selections: list[SelectionItem] = Field(..., min_length=1)
 

class SelectOut(BaseModel):
    run_id: str
    selections_path: str
    blueprint_path: str
    count: int

# --- force vs resume ---------------------------------------------------------
# Every billable stage carries both flags, and they mean opposite things:
#
#   force=True    throw away what is on disk and generate all of it again. Use
#                 after editing the blueprint — resume cannot see that a prompt
#                 changed, only that a file exists.
#   resume=True   keep every artifact already on disk and generate only what is
#                 missing. This is the recovery path for a stage that died part
#                 way through, and it is the one that saves money.
#
# Neither flag set keeps the original behaviour: a 409 if the stage already has
# output, so nothing billable can be re-run by accident. Setting BOTH is a 422 —
# they contradict each other and guessing which one the caller meant is exactly
# the kind of guess that spends someone's credits.
class AssetsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    force: bool = False                               # regenerate even if assets exist
    resume: bool = False                              # generate only missing PNGs

class AssetsOut(BaseModel):
    run_id: str
    assets_dir: str
    backgrounds: int
    storyboard: int
    reused: int = 0                                   # existing PNGs left untouched

class ScenesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    force: bool = False
    resume: bool = False          # keep clips already in veo_raw/; generate the rest
    tts_only: bool = False        # reuse veo_raw/ clips; re-run L6 only (no Veo)
    tts_provider: Literal["azure", "elevenlabs"] = "elevenlabs"
    video_provider: Literal["gemini", "kieai"] = "gemini"   # kieai = testing-only
    # Word-level timing for subtitles (both audio paths) and for placing audio
    # (Azure only). "gemini" is one billed call per speaking scene; "whisper" runs
    # faster-whisper locally for nothing, but needs the optional dependency
    # installed and downloads a model on first use. See docs/open-questions.md #16.
    diarizer: Literal["gemini", "whisper"] = "gemini"

class ScenesOut(BaseModel):
    run_id: str
    scenes_dir: str
    scenes: int
    total_cost_usd: float
    reused: int = 0               # scenes whose Veo call was skipped (resume)

class MusicIn(BaseModel):
    run_id: str
    duration_s: float | None = None   # hint only; Lyria 3 Clip fixes ~30s
    instrumental: bool = True
    force: bool = False               # overwrite an existing track.mp3
    resume: bool = False              # keep an existing track.mp3, generate if absent
 
 
class MusicOut(BaseModel):
    run_id: str
    music_path: str
    music_style: str
    regenerated: bool
    reused: bool = False              # resume found an existing track and kept it

class RenderIn(BaseModel):
    run_id: str
    force: bool = False   # overwrite an existing final.mp4
    # How the captions get burned in. "boxed" is the current default (PNG
    # overlays, rounded corners, one ffmpeg input per cue). "ass" draws the same
    # box as vector shapes in a single subtitle file — flat cost however many
    # cues, needs libass. ON TRIAL: render is free and re-runnable, so run both
    # on the same run_id and compare before changing the default.
    # See docs/open-questions.md #23.
    subtitle_method: Literal["boxed", "ass", "libass", "drawtext", "auto"] = "boxed"
 
 
class RenderOut(BaseModel):
    run_id: str
    scenes: int
    merged_path: str
    srt_path: str
    merged_subs_path: str
    final_path: str                    
    language: str                      # config.language the subtitles render in
    music: bool                        # was music_bg/track.mp3 mixed in
    font_warning: str | None = None    # set when the language needs a missing script font
