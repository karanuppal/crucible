# Phase 4 Adversarial Review — Second Pass

- Verdict: FAIL

## Status of prior 3 blockers

1. POST_MORTEM accepts free text with no binding
   - Status: FIXED
   - Evidence: `add_lesson(..., LessonSource.POST_MORTEM)` now requires `post_mortem_id`, and post-mortems must be created via typed `PostMortemRecord` in `record_post_mortem()`.

2. Provenance forgeable via arbitrary `source_run_id`
   - Status: STILL BLOCKING
   - Evidence: run-derived lessons now require registered `run_id`, and persisted lessons are re-validated on load.
   - Remaining gap: persisted `post_mortems` are loaded without validating that `triggering_run_id` is still a registered harness run. A tampered store can rewrite an existing post-mortem’s `triggering_run_id` to an unknown/fake run, and the store still loads successfully as long as the lesson references an existing `post_mortem_id`.
   - Repro:
     - Create valid run `real-run`
     - Create post-mortem bound to `real-run`
     - Create lesson bound to that `post_mortem_id`
     - Tamper JSON: rewrite `post_mortems[pm_id]["triggering_run_id"] = "forged-run"`
     - Reload store
     - Result: store loads; lesson remains injectable; post-mortem provenance is now forged

3. Machine profile fails on non-ImportError `psutil` errors
   - Status: FIXED
   - Evidence: `detect_machine_profile()` now catches all exceptions around memory detection and falls back safely. The new adversarial tests for `RuntimeError` and impossible memory values both pass.

## New findings

### 1) Remaining provenance forgery path via persisted post-mortem records (blocking)

`MemoryStore._load()` re-validates lesson provenance, but it does not validate loaded `PostMortemRecord.triggering_run_id` against `known_run_ids`.

Impact:
- Post-mortem-backed lessons can survive reload with forged upstream provenance.
- This weakens the claimed guarantee that “all lessons come from recorded run outcomes.”

Recommended fix:
- On load, validate every persisted post-mortem:
  - `triggering_run_id` must exist in `known_run_ids`
- Reject or quarantine any post-mortem with invalid triggering provenance before loading dependent lessons.
- Add a negative test for tampered post-mortem provenance on reload.

### 2) Intensity wrappers are improved but still bypassable (non-blocking, but real)

The wrapper normalization fixes the previously reported variants:
- `python -m pytest`
- `python3 -m pytest`
- `uv run pytest`
- `poetry run pytest`
- `pytest tests/unit`
- `pytest tests/ -q`
- `npm ci`
- `make test`

Those all now classify correctly, and the new adversarial scheduler tests pass.

However, several realistic shell-wrapper forms still fall through to `MEDIUM`:
- `env PYTHONPATH=src python -m pytest`
- `bash -lc 'pytest tests/'`
- `sh -lc 'pytest tests/'`
- `python -c "import pytest,sys; sys.exit(pytest.main(['tests/']))"`

Observed results:
- all four classified as `medium` via task-size fallback

Impact:
- A caller can still disguise full-suite test execution behind shell wrappers or inline Python.

Recommended fix:
- Normalize `env ...` prefixes and shell launcher wrappers (`bash -lc`, `sh -lc`, etc.)
- Consider a second-pass heuristic for embedded `pytest` tokens inside quoted shell commands / Python snippets
- Add fixture coverage for these forms if they matter in production usage

## Test run

Command run:
- `uv run pytest tests/scheduler/ tests/memory/ -v`

Result:
- 58 passed, 0 failed

## Signoff recommendation

- Do not sign off yet.
- Phase 4 is materially stronger than v1:
  - free-text post-mortem injection is closed
  - run-id validation exists
  - persisted lesson provenance is partially re-validated
  - machine profile fail-safe behavior is fixed
  - the originally reported intensity wrapper gaps are covered
- But the remaining persisted post-mortem provenance hole is still a real integrity failure, so the provenance blocker is not fully resolved.
- Recommended path to PASS:
  1. Validate `PostMortemRecord.triggering_run_id` on load
  2. Add a tampered-post-mortem reload test
  3. Optionally harden shell-wrapper intensity normalization before final signoff
