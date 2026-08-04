"""
This file contains the director configurations as well
the place to get the API keys from the env

Two things live here and nothing else:

  * DirectorConfig — every knob the director (L2) reads. The first seven fields
    come straight from the user's config.json (schemas.ConfigIn maps onto them
    1:1, by name — renaming a field here silently breaks that mapping in
    main.run_director, which does DirectorConfig(**config.json)). The last four
    are PACING knobs the user never sees; they are not in ConfigIn, so they can
    only be changed in code.

  * make_client — the single place the Gemini API key is read.

load_dotenv() runs at import, so anything importing app.config gets .env
loaded.
"""

import os
from google import genai
from dotenv import load_dotenv
from typing import Protocol
from dataclasses import dataclass
from app.schemas import AspectRatio, BlueprintType

load_dotenv()

@dataclass
class DirectorConfig:
    # --- user-supplied (mirrors schemas.ConfigIn field-for-field) ---
    language: str = "English"
    audience: str = "corporate learners"
    depth: str = "standard"
    objective: str = ""   # user-provided description of the video's goal
    style: str = (
        "modern flat 2D cartoon corporate explainer, bold clean outlines, "
        "cel-shading, muted color palette"
    )
    aspect_ratio: AspectRatio = "16:9"
    blueprint_type: BlueprintType = "opening"

    # --- pacing / length budget: prompt text AND validator thresholds ---
    # These decide the director's word ceiling per speaking scene:
    #   max_words = words_per_second * max_scene_seconds  (2.5 * 8 = 20 words)
    # build_director_prompt interpolates them into DIRECTOR_RULES, and
    # validate_blueprint re-derives the same number to reject over-long text.
    # Raising max_scene_seconds above 8 is NOT enough on its own — Veo only
    # emits 4/6/8s clips (video_veo_client.VEO_ALLOWED_SECONDS) and
    # scene_gen.VEO_VIDEO_SECONDS hard-codes 8s for speaking scenes.
    words_per_second: float = 2.5
    min_scene_seconds: float = 6.0
    max_scene_seconds: float = 8.0
    # Requested B-Roll length. Veo's floor is 4s, so B-Roll is generated at 4s
    # and trimmed down to this afterwards (see scene_gen.generate_scene).
    # NOTE: for blueprint_type="opening" the OPENING B-Roll ignores this and is
    # forced to 4s by director.enforce_opening_length, because it has to be long
    # enough to carry the title card.
    broll_length_seconds: float = 1

    # min_scene_seconds is interpolated into the prompt as `min_words` but is
    # not enforced by validate_blueprint — short scenes pass. Advisory only.


class DirectorLLM(Protocol):
    """The only thing the director needs from an LLM: one text completion.

    Keeping this a Protocol is what lets validate_blueprint / direct() be
    unit-tested against a stub that returns canned JSON — no key, no spend.
    GeminiDirector (director.py) is the live implementation.
    """
    def complete(self, system: str, user: str) -> str: ...

def make_client(api_key_env: str = "HEYHI_GEMINI_API_KEY"):
    """Construct the Gemini client from the environment. Credential edge:
    the key is read here and nowhere else, and is never printed or persisted."""
    key = os.environ.get(api_key_env)
    if not key:
        raise RuntimeError(f"{api_key_env} not set in environment")
    return genai.Client(api_key=key)