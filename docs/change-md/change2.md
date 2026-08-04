# Atlas — Source-to-Video Pipeline · Change Spec v1

**Status:** End-to-end pipeline is working; `change.md` is fully implemented.
The changes below are the next batch.
**Prime directive:** do not regress existing behaviour. See _Regression policy_
below for exactly what "no regression" means for each class of change — it is
**not** "byte-for-byte for everything," because some of these are bug fixes.

---

## NON-NEGOTIABLE — no stacking

**Do not fix a problem by adding code on top of the code that caused it.**

Layering a patch over a broken function hides the fault instead of removing it.
Every added wrapper, guard, or compensating branch makes the next fault harder
to locate and the layer after that harder to reason about. This pipeline already
has many layers; it cannot absorb accidental ones.

**Forbidden:**

- Wrapper functions whose only job is to correct the output of the function they wrap.
- Post-processing steps that undo or clean up something an earlier step should not have produced.
- `if` branches that special-case a symptom instead of fixing its cause.
- New helpers that duplicate logic already living elsewhere, because editing the original felt risky.
- `try/except` blocks that swallow a fault so the pipeline keeps moving.
- Dead code left in place "just in case" alongside its replacement.

**Required instead:**

1. **Locate the actual cause before writing anything.** Name the function and the
   line. If you cannot, say so and ask — do not compensate downstream.
2. **Fix it at the source.** Change the function that is wrong.
3. **Delete what the fix makes obsolete.** A change that only adds lines and never
   removes any is a warning sign — say why nothing was removed.
4. **Read the existing code before extending it.** Most of what you need is already
   implemented somewhere in the pipeline.
5. **State the trade-off when a clean fix is genuinely out of scope.** A deliberate,
   explained, temporary shim is acceptable; an unannounced one is not. Mark it
   `# TEMPORARY:` with the reason and the real fix.

This rule outranks speed of delivery. If the clean fix requires touching a file
outside the change's stated scope, do that — and say so in the summary.

**Tension with "don't touch the Azure path" (Change 1):** that is a _don't
refactor working code_ instruction, not a licence to wrap it. Adapt at the
interface; do not build a correction layer around it.

---

## Regression policy (read before implementing)

Not every change is gated the same way. Classify first, then apply the matching rule.

| Change class                                              | Rule                                                                                                                                  | Gating                                                                |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| **Bug fix** (behaviour is currently wrong)                | Correct it at the source. The _already-correct_ paths must stay byte-for-byte identical; the _broken_ path changes to become correct. | **No flag.** A bug fix hidden behind a default-off flag is not a fix. |
| **Additive feature** (new capability, opt-in)             | Ship behind a new parameter whose default reproduces today's output byte-for-byte.                                                    | **New param, default = today's behaviour.**                           |
| **New default behaviour** (you want the output to change) | This is a deliberate, scoped regression. It must be called out explicitly and confirmed — do not sneak it in under an additive flag.  | **Decision required** (see the change).                               |

When a change's class is ambiguous, stop and ask rather than guessing.

---

## How to use this spec

- Each change is self-contained: scope, root-cause target, requirement, gating,
  and acceptance criteria.
- **Files to read** lists are seeded with known entry points and marked
  `TODO:` where the exact path must be confirmed against the current tree. Fill
  these in before handing the change to Claude — an accurate file list is the
  single biggest lever on output quality.
- Do one change per PR/commit. Do not batch unrelated changes.

---

## Change 1 — ElevenLabs subtitles do not render (Azure works)

**Class:** Bug fix. **No new flag.**

**Symptom:** subtitles appear correctly when `tts_provider = azure` but are
absent when `tts_provider = elevenlabs`. Everything else about the ElevenLabs
output is fine.

**Root-cause target:** the subtitle track is built from timing data. Azure and
ElevenLabs almost certainly return that timing in different shapes (Azure TTS
emits word/character boundary events; the ElevenLabs speech path may return
timestamps in a different structure, a different unit, or not at all unless
requested). The fault is most likely in _where subtitle timings are sourced per
provider_, not in the subtitle renderer itself — the renderer works for Azure,
so it is downstream and correct. **Find the function that produces subtitle
timing for the ElevenLabs branch and confirm what it actually returns before
writing anything.**

**Constraints:**

- Do **not** modify the Azure timing/subtitle path. It stays byte-for-byte.
- Do **not** wrap the subtitle renderer to "handle the ElevenLabs case." Fix the
  timing source so both providers hand the renderer the same shape. Adapt at the
  interface (Change's _no stacking_ rule).
- If ElevenLabs simply is not returning timestamps, the fix is to request/derive
  them at the source (the TTS call), not to fabricate them after the fact.

**Files to read:**

- The `tts_provider` dispatch on `/pipeline/scene` (azure | elevenlabs). `TODO: confirm module.`
- The ElevenLabs speech integration (the speech-to-speech client). `TODO: path.`
- The subtitle/caption builder + the compositor that burns subtitles (moviepy-based). `TODO: path.`
- The Azure TTS path, **read-only**, as the reference for the correct timing shape.

**Acceptance criteria:**

- With `tts_provider = elevenlabs`, subtitles render with correct timing on a test scene.
- With `tts_provider = azure`, output is unchanged (byte-for-byte / hash match on a fixed input).
- The subtitle renderer has one code path, not a per-provider branch inside it.
- The summary names the function and line that was actually wrong.

---

## Change 2 — Cartoon title "wave-in" animation

**Class:** Decision required (see gating). **Scope:** `style_type = cartoon` opening only.

**Requirement:** the title's **in-animation** for cartoon style is a
left-to-right wave. Each letter, in sequence from left to right, bounces up
slightly then settles back down, with the next letter following one beat later —
producing a travelling wave across the word.

**Decision:**

- **New default for cartoon** — every cartoon opening gets the wave. This is a
  deliberate visual change to cartoon output; confirm it and note it as such.

**Files to read:**

- The opening-section treatment driven by `style_type` (cartoon branch). `TODO: path.`
- Wherever title text animation timing/keyframes are defined for the opening. `TODO: path.`

**Acceptance criteria:**

- Cartoon title letters animate in as a left-to-right travelling wave with a
  consistent per-letter delay.
- Realism and semi-realism openings are untouched.

---

## Change 3 — Cartoon title idle "bounce" (persistent, post-in-animation)

**Class:** Decision required (same as Change 2). **Scope:** `style_type = cartoon` opening only.

**Requirement:** after the wave-in (Change 2) completes, the title does **not**
go static. Each word/letter holds a subtle continuous up-and-down bounce (idle
loop) for the remainder of its on-screen time.

**Dependencies / interface with Change 2:** the in-animation and the idle loop
must hand off cleanly — the idle bounce starts from the resting position the
wave-in ends on, with no visible jump. Define the handoff explicitly; do not add
a corrective frame to paper over a mismatch (_no stacking_).

**Gating decision:** tie to the same decision made in Change 2. If Change 2's decision
is new default for cartoon then add in the idle "bounce" to the "wave-in" animation already added in change 2

**Files to read:** same as Change 2.

**Acceptance criteria:**

- After wave-in, the title loops a subtle idle bounce with no positional jump at handoff.
- The loop is bounded to the title's visible duration.

---

## Change 4 — Opening overlay MP4 at 0.3s

**Class:** Additive feature. **Gated, default = no overlay.**

**Requirement:** composite an opening overlay MP4 onto the video, starting **0.3s
from the start**. Overlay files live at `root:asset/overlays/`.

**Design:**

- New parameter (e.g. `opening_overlay = <filename in asset/overlays> | none`),
  **default `none`** → today's output byte-for-byte.
- Start offset **0.3s** — confirm whether this is fixed or should be a companion
  param (e.g. `opening_overlay_offset`, default `0.3`).
- Confirm the overlay's blend/composite mode and whether it carries alpha or is a
  greenscreen keyed layer (note: the pipeline already plans a greenscreen overlay
  at topic boundaries — reuse that compositing path if it fits rather than
  writing a second overlay compositor. _No duplicated logic._).
- This opening overlay is only if the style_type is "cartoon", the style_type of realism/ semi-realism remains untouched

**Files to read:**

- The final compositor / layer-assembly stage (moviepy). `TODO: path.`
- The existing/planned greenscreen-overlay compositing code, if present, to reuse. `TODO: path.`
- Config layer where opening-section params are declared (near `blueprint_type`, `style_type`). `TODO: path.`

**Acceptance criteria:**

- With `opening_overlay = none` (default), output is byte-for-byte unchanged.
- With an overlay set, it composites starting at 0.3s using the same overlay
  compositor as the topic-boundary greenscreen (no second implementation).
- Missing/invalid overlay filename fails loudly with a clear error — it is **not**
  swallowed so the pipeline "keeps moving."

---

## Definition of done (every change)

- [ ] Root cause named (function + line) before code was written.
- [ ] Fix is at the source; no wrapper/branch/post-process compensating for it.
- [ ] Obsolete code deleted, or an explicit reason given for keeping it.
- [ ] Default path (per Regression policy) verified unchanged on a fixed input.
- [ ] Any `# TEMPORARY:` shim is annotated with reason + real fix.
- [ ] Summary states what was removed and any out-of-scope file that had to change.
