# Phase 4 Adversarial Review — Third Pass

- Verdict: PASS

## Summary

This third-pass review re-checked the two remaining areas from v2:
- persisted post-mortem provenance validation on reload
- wrapper normalization for heavy-command classification

I also re-ran the targeted test suites and performed fresh adversarial probes beyond the newly added fixtures.

Test run:
- `uv run pytest tests/scheduler/ tests/memory/ -v`
- Result: `63 passed, 0 failed`

Targeted tamper probe:
- Forged `post_mortems[pm_id].triggering_run_id = "forged-run"` in persisted JSON
- Reload result: correctly rejected with `HostMemoryLeakError`

Targeted wrapper probes:
- Confirmed HEAVY: `bash -lc 'pytest tests/'`, `sh -c 'pytest tests/'`, `env PYTHONPATH=src python -m pytest`, `python -c 'import pytest; pytest.main()'`, plus the previously covered `python -m pytest`, `uv run pytest`, `poetry run pytest`, `npm ci`, `make test`, etc.

## Blocker table

- Original blocker 1: POST_MORTEM accepted free text with no harness-owned binding
  - Status: FIXED
  - Evidence:
    - `LessonSource.POST_MORTEM` now requires `post_mortem_id`
    - post-mortems are created as typed `PostMortemRecord`s via `record_post_mortem()`
    - `add_lesson()` rejects missing/unknown post-mortem IDs

- Original blocker 2: Lesson provenance forgeable via arbitrary `source_run_id`
  - Status: FIXED
  - Evidence:
    - run-derived lessons require `source_run_id` to exist in `known_run_ids`
    - `_load()` re-validates persisted lesson provenance
    - newly tested: `_load()` now also validates each persisted post-mortem `triggering_run_id` against `known_run_ids`
    - forged JSON reload is rejected before dependent lessons become injectable

- Original blocker 3: Machine profile detection not fail-safe on non-`ImportError` telemetry failures
  - Status: FIXED
  - Evidence:
    - adversarial tests for runtime failure and impossible memory values pass
    - prior v2 blocker is closed and remains closed in this pass

- New finding: additional shell-wrapper bypasses still exist outside the implemented normalization set
  - Status: NON-BLOCKING
  - Evidence:
    - `zsh -lc 'pytest tests/'` => `medium`
    - `fish -c 'pytest tests/'` => `medium`
  - Assessment:
    - This is a real residual heuristic gap, but it does not invalidate the Phase 4 acceptance criteria that were previously blocked.
    - The explicitly identified bypass classes from v2 are now covered:
      - `bash -lc ...`
      - `sh -c/-lc ...`
      - `env ... python -m pytest`
      - `python -c ... pytest ...`
    - The scheduler’s intensity classifier remains heuristic-based rather than parser-complete. That is acceptable for Phase 4 if documented as such.

## Verification against requested checks

1. Post-mortem reload validation works
- PASS
- Tampering persisted `triggering_run_id` causes reload failure with `HostMemoryLeakError`

2. All wrapper variants now classified HEAVY
- PASS for the variants explicitly called out in the task and prior review
- Confirmed HEAVY:
  - `bash -lc 'pytest'`
  - `env PYTHONPATH=src python -m pytest`
  - `python -c "...pytest..."`
  - plus the earlier wrapper set already added to tests

3. Any new bypass paths?
- Yes
- Newly observed residual bypasses:
  - `zsh -lc 'pytest tests/'`
  - `fish -c 'pytest tests/'`
- These are worth hardening next, but I do not consider them Phase 4 blockers.

## Signoff recommendation

- Recommend signoff: YES
- Rationale:
  - All 3 original blockers are now closed.
  - The previously blocking persisted post-mortem provenance hole is genuinely fixed, both in code and in tests.
  - The named wrapper-bypass families from v2 are now correctly classified HEAVY.
  - The full targeted suite passes cleanly (`63/63`).

## Follow-up hardening (post-signoff)

- Extend shell-wrapper normalization to additional shells:
  - `zsh -lc ...`
  - `fish -c ...`
- Consider documenting classifier scope explicitly:
  - heuristic normalization for common wrappers, not full shell parsing
- Add two regression fixtures for the above residual cases if they matter in expected production traffic
