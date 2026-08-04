# Example runs

Text artifacts from three real runs, kept as documentation. The video files they
came with were deleted — they're regenerable and prove nothing a blueprint doesn't.

These live here rather than in `_storage/` because **`_storage/` is gitignored**. A
new contributor clones the repo and sees none of it, so anything meant to be
documentation has to be committed.

| Run | style_type | Voice source | Scenes | Chars | Demonstrates |
|---|---|---|---|---|---|
| `run_0616c9e5` | realism | `index` (Azure names) | 9 | 1 | The fullest example. Multi-topic, five storyboards, closing B-Roll per topic. Also carries a legacy `keyframe` key. |
| `run_d852054a` | realism | `elevenlabs` | 2 | 1 | Minimal. `audio_id` **is** the ElevenLabs voice_id — no library lookup. |
| `run_ff808532` | cartoon | `elevenlabs` | 3 | 1 | The `cartoon` title treatment: no scrim, per-letter wave animation. |

All three are `blueprint_type: "opening"` and `language: "english"`. There is no
committed example of a `summary` run.

## What each file is

| File | What it shows |
|---|---|
| `config.json` | Exactly what L1 stores. Maps 1:1 onto `DirectorConfig`. |
| `blueprint.placeholder.json` | The director's **pristine** output, with semantic placeholder ids (`char_narrator`, `char_HR_rep`). |
| `blueprint.json` | The **resolved** blueprint after `/pipeline/select` patched it. |
| `selections.json` | The placeholder → library-id + voice mapping. |

### ⚠ Two of these were hand-truncated — use `run_d852054a` for diffs

| Run | `blueprint.placeholder.json` | `blueprint.json` |
|---|---|---|
| `run_0616c9e5` | 16 scenes | **9** — tail removed by hand |
| `run_ff808532` | 26 scenes | **3** — tail removed by hand |
| `run_d852054a` | 2 scenes | 2 ✅ |

In both truncated runs the resolved blueprint is a strict prefix of the snapshot.
`apply_selection` never adds or removes scenes — it rewrites ids in place — so this
was manual editing, almost certainly to cap Veo spend while testing. Kept as-is
because it is honest evidence of how the pipeline gets used.

Side effect worth knowing: both truncated runs now end on a *speaking* scene with
no closing B-Roll. That still validates clean (see
[open-questions #7](../open-questions.md), final-topic gap) and means the renderer
places no transition at the end.

So to see what `patch_blueprint.apply_selection` actually does, diff
**`run_d852054a`**, where the two files describe the same 2 scenes:

```bash
diff <(jq -S . docs/examples/run_d852054a/blueprint.placeholder.json) \
     <(jq -S . docs/examples/run_d852054a/blueprint.json)
```

You'll see `characters`, `audios[].char_id` and `storyboard[].reference` rewritten,
and `prompt` untouched — which is
[bug #1](../open-questions.md#1-placeholder-char_ids-leak-into-veo-prompts), visible
in all three runs.

## Schema drift

`run_0616c9e5` still carries a top-level `keyframe` key. It is **not** in
`VideoBlueprint`; pydantic drops unknown keys on parse, so it's inert. Kept
deliberately as evidence that `_storage/` held several blueprint generations and
nothing migrates old runs. See
[open-questions.md #5](../open-questions.md#5-schema-drift-between-the-code-the-docs-and-blueprints-on-disk).

## Regenerating

These are inputs to nothing — no code reads `docs/`. To make a run usable again,
copy a directory into `_storage/atlas_storyboard/` and re-run from
`/pipeline/assets` onward. Everything before that is already done.
