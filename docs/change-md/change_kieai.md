## Change: Add kie.ai as a temporary, toggleable video-generation provider (testing only)

### Objective

Add kie.ai as an alternative to the official Gemini API for video generation,
used only during testing. This is a temporary, additive change.

### Hard constraints

- **Do NOT replace or modify the existing Gemini path.** It stays the default
  and remains fully functional.
- Make the provider selectable via a flag (e.g. `video_provider = gemini | kieai`),
  following the existing pluggable-provider pattern (cf. `tts_provider`).
  Gemini path untouched; kie.ai is opt-in.
- Keep the kie.ai integration cleanly isolated so it's trivial to remove later.

### Reference (source of truth for kie.ai)

- `test_video_kieai.py` (attached) — working kie.ai implementation. Use it as the
  authoritative contract for the kie.ai request/response shape and auth.

### Known difference to design around

- **File upload:** kie.ai accepts URLs only — no local/binary upload. Local assets
  must be exposed as URLs before the call. Confirm the hosting mechanism
  (upload to storage → return URL) rather than assuming one; flag if none exists.

### Verify, don't assume

- Recheck parameter/behaviour parity between Gemini and kie.ai: auth, model/version
  params, prompt fields, aspect ratio, duration, and sync-vs-async/polling and
  response shape. Surface any mismatch explicitly instead of silently mapping it.

### Code quality

- Fix at the source: introduce one clean provider abstraction both paths share.
  Do not wrap or stack code to paper over the differences.

### Acceptance criteria

- With the flag on default, the Gemini path behaves exactly as before.
- Setting the flag to `kieai` runs the pipeline end-to-end via kie.ai.
- No duplicated pipeline logic — only the provider call differs.
