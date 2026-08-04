# Atlas — Source-to-Video Pipeline · Change Spec v1

**Status:** end-to-end pipeline is working. These are additive changes.
**Prime directive:** do not regress existing behaviour. Every change is gated
behind a new parameter whose default reproduces today's output byte-for-byte —
_unless_ a change is explicitly marked as a cutover, in which case the old code
path is deleted (see the ⚠ blocks below).
**Working agreement:** before editing anything, read the source files named in
_Context_ and confirm the current behaviour. Do not code against this spec's
description of the code — code against the code.

---

## NON-NEGOTIABLE — no stacking

**Do not fix a problem by adding code on top of the code that caused it.**

Layering a patch over a broken function hides the fault instead of removing it.
Every added wrapper, guard, or compensating branch makes the next fault harder
to locate. This pipeline already has five layers; it cannot absorb accidental
ones.

Forbidden:

- Wrapper functions whose only job is to correct the output of the function they wrap.
- Post-processing that undoes something an earlier step should not have produced.
- `if` branches that special-case a symptom rather than fix its cause.
- New helpers that duplicate logic already living elsewhere because editing the original felt risky.
- Try/except blocks that swallow a fault so the pipeline keeps moving.
- Dead code left "just in case" alongside its replacement.

Required instead:

1. **Locate the actual cause before writing anything.** Name the function and the line. If you cannot, say so and ask — do not compensate downstream.
2. **Fix it at the source.** Change the function that is wrong.
3. **Delete what the fix makes obsolete.** A change that only adds lines and never removes any is a warning sign — say why nothing was removed.
4. **Read the existing code before extending it.** Most of what you need is already implemented somewhere in the pipeline.
5. **State the trade-off when a clean fix is genuinely out of scope.** A deliberate, explained shim is acceptable. An unannounced one is not. Mark it `# TEMPORARY:` with the reason and the real fix.

This rule outranks speed of delivery. If the clean fix requires touching a file
outside the change's stated scope, do that — and say so in the summary.

---

## Context Claude needs first

**What Atlas is:** a source-to-video pipeline (codename Atlas, env
`heyhi_atlas_ai_video`) that turns corporate training documents into
AI-generated videos. Part of HeyHi (Singapore-based adaptive-education platform).

**Stack / layers relevant here:**

- Scripting/blueprint: Gemini 2.5 Flash. `director.py` is the L2 layer (schema v3) that builds `blueprint.json` from source + config.
- Video: Veo 3.1.
- **Audio/TTS: pluggable — Azure TTS and ElevenLabs.** A `tts_provider` (`azure | elevenlabs`) selection is planned/present on `/pipeline/scene`; **the Azure path must stay untouched by these changes.** Everything below is the **ElevenLabs path only.**
- ElevenLabs is **already integrated** (speech-to-speech was wired in earlier). An ElevenLabs client + API key already exist in the codebase. **Reuse them — do not instantiate a second client or add a second key.** <!-- FILL: module/path of the existing ElevenLabs client + the env var name for the key -->

**Endpoints in scope:**

- `GET /pipeline/audios` — returns the list of selectable voices. <!-- FILL: file + handler function -->
- `POST /pipeline/select` — records the chosen voice for a scene/blueprint. <!-- FILL: file + handler function; and where audio_id currently flows to -->

**Current audio source of truth (being replaced):** a local audio-library
`index.json`. `/pipeline/audios` reads it; `/pipeline/select` currently takes an
`audio_id` that is a key into it. <!-- FILL: path to index.json + its per-entry shape (id, name, file, …) + the loader function name -->

**ElevenLabs `GET /v2/voices` reference (verified 2026-07):**

- Auth header: `xi-api-key`. Base URL `https://api.elevenlabs.io`.
- **Paginated.** Query params: `page_size` (≤100, default 10), `next_page_token`, `search`, `sort`, `sort_direction`, `voice_type`, `category`, `voice_ids` (lookup ≤100), `include_total_count`. Loop on `next_page_token` while `has_more` is true — a single call does **not** return everything.
- Response top level: `{ voices: [...], has_more, total_count, next_page_token }`.
- Per-voice fields that matter: `voice_id`, `name`, `preview_url`, `category` (`premade|cloned|generated|professional`), `labels` (free-form map), `verified_languages` (array of `{language, model_id, accent, locale, preview_url}`), `available_for_tiers`.
- **Voice scope:** default (`voice_type` unset) returns the workspace's personal + default premade voices. The shared community library needs `voice_type=community` — **and is not available via the API on the free tier.** Decide which scope `/audios` should surface (see Change 1, Decision A).

---

# Change 1 — `/pipeline/audios` reads live ElevenLabs voices

**Goal:** `/pipeline/audios` stops reading the local `index.json` and instead
returns the live list from `GET /v2/voices`, shaped so the front end can filter
by language and gender.

**Implementation notes (no-stacking applies):**

- Replace the `index.json` loader that backs this endpoint — do **not** wrap it or translate its output. The ElevenLabs call becomes the source of truth for this list.
- Reuse the existing ElevenLabs client (see _Context_).
- Paginate to completion before returning (loop `next_page_token` / `has_more`).
- **Derive filter tags defensively — these fields are often missing:**
  - `language`: read from `verified_languages[].language` (with `locale`/`accent` if you want finer labels). A voice can list several. Fall back to `labels.language` if present. If nothing, tag `unknown` — do not crash or drop the voice.
  - `gender`: read from `labels.gender`. Frequently absent → `unknown`.
- Return per voice at minimum: `voice_id`, `name`, `preview_url`, `languages[]`, `gender`. <!-- FILL: confirm the exact shape the front end expects so the contract stays stable -->

**Embedded question, answered:** yes — the API gives you the tags you wanted.
Gender comes from `labels.gender`; language from `verified_languages`
(structured) or `labels.language`. Both are nullable, so treat them as
best-effort tags, not guarantees.

### ⚠ Decision A — "Southeast Asia region" is not a real voice filter

The v2/voices list is **not region-scoped** and there is no "Southeast Asia"
region for voices. In ElevenLabs "region" means one of two unrelated things,
neither of which filters the voice list:

1. **Backend serving region** (USA / Netherlands / Singapore) — auto-routed for latency, reported in the `x-region` response header. Same voices everywhere.
2. **Data-residency environment** (US default, EU, India, Singapore for Enterprise) — chosen via a different base URL; about _where data is stored_, not which voices exist.

So "filter to voices available in the SEA region" cannot be implemented as
written. Pick the real intent before coding:

- **A1 (most likely, given HeyHi's market):** filter by **language** — e.g. surface only voices whose `verified_languages` include the languages you serve (English, Chinese, and SEA languages such as Indonesian / Malay / Filipino / Thai / Vietnamese). This is a front-end/back-end filter on the tags above, not a "region."
- **A2:** you actually want requests _routed_ through the Singapore backend / data-residency for latency or compliance. That's a base-URL/config change on the ElevenLabs client, **independent of this endpoint**, and does not change which voices are returned. Track it separately if you need it.

**Do not proceed on Change 1 until A1 vs A2 is chosen.** Default assumption if
unspecified: **A1, language filter.**

### ⚠ Decision B — additive gate vs cutover

The prime directive says gate behind a param defaulting to old behaviour; this
change as written _replaces_ the source. Choose one and mark it in code:

- **B1 (additive, prime-directive-compliant):** add `voice_source` (`index | elevenlabs`, default `index`). Old callers unchanged; new UI passes `elevenlabs`. Keep the `index.json` path alive until the UI is migrated.
- **B2 (cutover):** delete the `index.json` list path entirely now. Cleaner, but the front end and `/pipeline/select` (Change 2) must land in the same PR or you'll break selection.

Recommendation: **B1 during development, flip to B2 (deleting the index path)
once the UI sends ElevenLabs ids end-to-end.** State which you took in the PR.

### Acceptance

- `/pipeline/audios` returns live ElevenLabs voices, fully paginated, each carrying `voice_id`, `name`, `preview_url`, `languages[]`, `gender`.
- Missing labels never crash the endpoint or drop a voice.
- Azure path and any non-audio route are byte-for-byte unchanged.
- Under B1: default (`voice_source=index`) reproduces today's response exactly.

---

# Change 2 — `/pipeline/select` receives an ElevenLabs voice id directly

**Goal:** the id `/pipeline/select` accepts is no longer an `index.json` key —
it is an ElevenLabs `voice_id` (28-char alphanumeric, e.g.
`21m00Tcm4TlvDq8ikWAM`), stored and passed straight to the ElevenLabs TTS call.

**Implementation notes (no-stacking applies):**

- **One gate, two touchpoints.** `index.json` is read in _both_ `/audios` (the list, Change 1) and `/select` (the resolution, here). They move together under the **same** Decision B gate: under **B1** the index resolution stays behind `voice_source=index`; under **B2** it is deleted. Do not delete it here while Change 1 keeps the index list alive — that would strand any index-based selection.
- **On the ElevenLabs path there is no resolution step** (unconditional, no-stacking): the `voice_id` flows unchanged into the existing ElevenLabs TTS call on the speech path. **Never add a translation layer** that maps an ElevenLabs id back onto an index entry — that shim is the forbidden stacking, gate or no gate.
- Validation: either verify the id against the live `/v2/voices` set, or pass through and let the ElevenLabs TTS call surface its `422` on a bad id — **do not** swallow that error to keep the pipeline moving (see no-stacking rule 5). Pick one and say which.
- This is the mirror of Change 1: once `/audios` emits ElevenLabs ids, `/select` naturally receives them.

### ⚠ Contract note

If you rename the field `audio_id → voice_id` for clarity, that's a breaking
change to the front-end contract — do it deliberately and update the caller in
the same PR, or keep the name `audio_id` and only change its _meaning_. Don't
leave the field half-renamed. <!-- FILL: does the front end / blueprint schema persist this id anywhere (blueprint.json)? If so it must migrate too. -->

### Acceptance

- `/pipeline/select` accepts an ElevenLabs `voice_id` and the downstream TTS call uses it directly, with no `index.json` lookup in the path.
- A previously-selectable index id no longer resolves (B2) **or** still resolves under the old `voice_source` (B1) — whichever gate Change 1 used; the two changes must agree.
- Azure `tts_provider` path unaffected.

---

## Cross-change checklist

- [ ] A1/A2 resolved (Change 1) and B1/B2 resolved (both changes agree).
- [ ] All `<!-- FILL -->` markers replaced with real repo facts.
- [ ] Existing ElevenLabs client reused; no second client or key added.
- [ ] Pagination loops to completion.
- [ ] `index.json` audio-list code deleted where the fix made it obsolete (or explicitly kept behind the B1 gate, with a note).
- [ ] Azure TTS path untouched; diff limited to the ElevenLabs path + the two routes.
- [ ] PR summary states: which gate, what was deleted, and any deliberate `# TEMPORARY:` shim.
