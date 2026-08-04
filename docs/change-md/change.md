# Atlas — Source-to-Video Pipeline · Change Spec v1

**Status:** end-to-end pipeline is working. These are additive changes.
**Prime directive:** do not regress existing behaviour. Every change below is
gated behind a new parameter with a default that reproduces today's output
byte-for-byte.

---

## NON-NEGOTIABLE — no stacking

**Do not fix a problem by adding code on top of the code that caused it.**

Layering a patch over a broken function hides the fault instead of removing it.
Every added wrapper, guard, or compensating branch makes the next fault harder
to locate and the layer after that harder to reason about. This pipeline already
has five layers; it cannot absorb accidental ones.

Forbidden:

- Wrapper functions whose only job is to correct the output of the function
  they wrap.
- Post-processing steps that undo or clean up something an earlier step should
  not have produced.
- `if` branches added to special-case a symptom rather than fix its cause.
- New helpers that duplicate logic already living elsewhere, because editing the
  original felt risky.
- Try/except blocks that swallow a fault so the pipeline keeps moving.
- Dead code left in place "just in case" alongside its replacement.

Required instead:

1. **Locate the actual cause before writing anything.** Name the function and
   the line. If you cannot, say so and ask — do not compensate downstream.
2. **Fix it at the source.** Change the function that is wrong.
3. **Delete what the fix makes obsolete.** A change that only adds lines and
   never removes any is a warning sign — say why nothing was removed.
4. **Read the existing code before extending it.** Most of what you need is
   already implemented somewhere in the pipeline.
5. **State the trade-off when a clean fix is genuinely out of scope.** A
   deliberate, explained, temporary shim is acceptable. An unannounced one is
   not. Mark it `# TEMPORARY:` with the reason and the real fix.

This rule outranks speed of delivery. If the clean fix requires touching a file
outside the change's stated scope, do that — and say so in the summary.

Note the tension with the "do not touch the Azure path" constraint in Change 1:
that is a _don't refactor working code_ instruction, not a licence to wrap it.
Adapt it at the interface; do not build a correction layer around it.

---

## Context Claude needs first

Read these before writing code:

| File                                    | Why                                                                                                                                           |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/director.py`                       | L2 — builds `blueprint.json`. Holds `DIRECTOR_RULES`, `parse_blueprint`, `validate_blueprint`. **This file is populated (~30KB), schema v3.** |
| `app/schemas.py`                        | `VideoBlueprint`, `Scene`, `AspectRatio` pydantic models                                                                                      |
| `app/config.py`                         | `DirectorConfig`, `DirectorLLM`                                                                                                               |
| `app/tts/azure.py` (current TTS module) | Reference for the provider interface in Change 1                                                                                              |
| `patch_blueprint.py` (L3)               | Enforces invariants downstream; some validator rules mirror it                                                                                |
| Render/compositing layer                | Owns overlay burn-in (opening title, greenscreen)                                                                                             |

**Attachment status:** `director.py` is attached. `eleven_labs.py` is referenced
in the original brief but **was not provided** — request it before implementing
Change 1, or Claude will invent the ElevenLabs client surface.

---

## Change 1 — Pluggable TTS provider (Azure | ElevenLabs)

**Goal:** add ElevenLabs as a second TTS backend without touching the Azure path.

### Requirements

1. New module `app/tts/eleven_labs.py` containing all ElevenLabs logic.
   Use the attached `eleven_labs.py` as the reference implementation.
2. `POST /pipeline/scene` accepts a new parameter:
   ```
   tts_provider: Literal["azure", "elevenlabs"] = "azure"
   ```
3. `"azure"` → existing code path, **unchanged**. Do not refactor it.
4. `"elevenlabs"` → new path in `eleven_labs.py`.

### Design constraint

Introduce a `TTSProvider` protocol so both modules satisfy the same interface
and the endpoint dispatches on a dict lookup, not an `if/else` chain that grows
per provider:

```python
class TTSProvider(Protocol):
    def synthesize(self, text: str, voice_id: str, **kw) -> bytes: ...

PROVIDERS = {"azure": AzureTTS, "elevenlabs": ElevenLabsTTS}
```

Wrap the existing Azure implementation in an adapter rather than rewriting it.

### Open questions (answer before implementing)

- **Voice mapping.** Blueprint scenes carry semantic `audio_id`s
  (`"audio_teacher_voice"`). Azure and ElevenLabs have different voice ID
  namespaces. Where does the `audio_id → provider voice ID` mapping live —
  config, a lookup table, or the request payload?
- **Failure mode.** If ElevenLabs errors (quota, 5xx), does the pipeline fail
  the scene, or fall back to Azure?
- **Output contract.** Must ElevenLabs return the same container/sample rate as
  Azure so the mux step is unchanged?

### Acceptance

- Existing Azure requests with no `tts_provider` produce identical output.
- Adding a third provider requires only a new module + one `PROVIDERS` entry.

---

## Change 2 — Replace transition B-Roll with a greenscreen overlay

**Goal:** topic boundaries are no longer marked by a generated B-Roll clip. They
are marked by the same greenscreen overlay already used after the opening B-Roll.

### What changes

- Blueprints stop emitting scenes with `broll_role = "topic-transition"`.
- At every topic change, the render layer composites the greenscreen overlay
  instead. Reuse the existing post-opening-B-Roll overlay path — same asset,
  same chroma key, same timing logic.

### DECISION REQUIRED — how deep does the removal go?

The original brief says "no longer have b-roll transition" but does not say
whether `"topic-transition"` disappears from the data model. Pick one:

- **Option A — schema removal.** Drop `"topic-transition"` from the `broll_role`
  Literal in `schemas.py`. Cleanest, but breaks deserialization of every
  existing blueprint on disk. Needs a migration.
- **Option B — generation removal (recommended).** Keep the Literal for backward
  compatibility. Stop the director from _producing_ the value, and have the
  render layer treat any legacy `"topic-transition"` scene as an overlay.

### Touch points in `director.py`

Everything below currently assumes transition B-Rolls exist and must be updated:

- `DIRECTOR_RULES` → the `broll_role` enum line in the scene shape block.
- `DIRECTOR_RULES` → **AI RULE #4** ("B-ROLL IS FOR TOPIC BOUNDARIES") — this
  rule's premise is now obsolete; rewrite it.
- `DIRECTOR_RULES` → "B-ROLL CONTINUITY" section, `OPENING / TOPIC-TRANSITION`
  block.
- `DIRECTOR_RULES` → "TIMELINE RULES OF THUMB", the B-Roll placement bullets.
- `validate_blueprint` → the `elif s.broll_role in ("opening", "topic-transition")`
  branch (~L501).
- `validate_blueprint` → the trailing "B-Roll between two video-with-audio scenes
  sharing topic" check (~L604), which is scoped to the same two roles.

### Open questions

- **Closing B-Roll interaction.** Today a closing B-Roll may sit immediately
  before a transition B-Roll. With transitions gone, does the closing B-Roll
  still fire at every topic end, or only at video end?
- **Overlay source.** Is the greenscreen asset a fixed file, or per-`style_type`
  (see Change 4)? Give Claude the path.
- **Duration.** Does the overlay consume timeline time, or overlap the adjacent
  clips?

### Acceptance

- A generated blueprint with ≥3 topics contains zero `"topic-transition"`
  scenes and renders with an overlay at each boundary.

---

## Change 3 — `blueprint_type` in the configuration layer

**Goal:** support a second, shorter blueprint shape for summary videos.

Add to `DirectorConfig`:

```python
blueprint_type: Literal["opening", "summary"] = "opening"
```

|                                        | `"opening"` (default, current behaviour) | `"summary"`           |
| -------------------------------------- | ---------------------------------------- | --------------------- |
| Opening B-Roll                         | 4s, exactly                              | 1–2s                  |
| Opening section (overlay + title burn) | Yes                                      | **None**              |
| `title` on screen                      | Yes                                      | **Not rendered**      |
| Flow                                   | opening B-Roll → title → scenes          | short B-Roll → scenes |

### Open questions

- **Is `title` still required in the schema for summary?** Recommendation: keep
  the field required (downstream metadata, filenames) but skip the burn-in. If
  it should become nullable, that's a schema change and a validator change.
- **Where is the 4s constant enforced?** `config.broll_length_seconds` feeds
  `DIRECTOR_RULES` as `%(broll_s)s` and the validator checks
  `s.length <= config.max_scene_seconds`. For summary, the opening B-Roll needs
  its own 1–2s bound distinct from other B-Rolls — a per-role length rule, not a
  global one.

### Acceptance

- `blueprint_type="opening"` output is unchanged from today.
- `blueprint_type="summary"` produces a blueprint whose first scene is a
  1–2s B-Roll, with no title overlay in the render.

---

## Change 4 — `style_type` at the top of the blueprint schema

**Goal:** the opening section's visual treatment varies by art style.

Add to `VideoBlueprint`, top level:

```python
style_type: Literal["realism", "cartoon", "semi-realism"]
```

### Opening section per style_type

**`cartoon`**

- Opening B-Roll plays clean: **no black overlay, no dimming**.
- Title text centred over it.
- Font: playful/display face suited to cartoon.
- Fill = a non-white colour; outline = white.
- Animation: bouncy, pop-in, high energy.

**`realism` / `semi-realism`**

- Current behaviour: 4s opening B-Roll, black overlay, background dimmed.
- Title text centred.
- Fill = white; outline = an accent colour (light blue / pink).
- Animation: simple rise or fade-in.

### Derivation from `style`

`style_type` is derived from the free-text top-level `style` field.

**Match order matters — check `semi-realism` first.** A naive
`if "realism" in style` matches `"semi-realism"` and mislabels it:

```python
def derive_style_type(style: str) -> StyleType:
    s = style.lower()
    if "semi-realism" in s or "semi realism" in s:
        return "semi-realism"
    if "cartoon" in s:
        return "cartoon"
    if "realism" in s or "realistic" in s:
        return "realism"
    return DEFAULT_STYLE_TYPE  # decide this
```

### Acceptance

- Cartoon openings render with no dim layer; realism openings are unchanged
  from today.

---

## Cross-cutting checklist

- [ ] `schemas.py` updated: `style_type` added; `broll_role` decision from Change 2 applied.
- [ ] `config.py` updated: `blueprint_type`, `tts_provider` defaults.
- [ ] `DIRECTOR_RULES` prompt updated for Changes 2, 3, 4 — the prompt and the
      validator must agree, or generation loops on validation failures.
- [ ] `validate_blueprint` updated for the same three changes.
- [ ] `patch_blueprint.py` (L3) checked for the same invariants.
- [ ] Render layer updated: greenscreen at topic boundaries, per-`style_type`
      title treatment, summary-mode opening skip.
- [ ] Regression test: existing config (`opening` + `azure`) produces unchanged output.
- [ ] No compensating/wrapper code added — every fix is at its source.
- [ ] Code made obsolete by these changes has been deleted, not commented out.
- [ ] Any temporary shim is marked `# TEMPORARY:` with a reason.
