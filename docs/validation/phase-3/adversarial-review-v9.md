# Adversarial Review — Phase 3 Validation and Review Foundation (v9)

Verdict: PASS

## Summary

I re-read the prior v8 review at `docs/validation/phase-3/adversarial-review-v8.md`, re-reviewed the current reviewer-boundary implementation in `src/agentic_harness/validation/reviewer.py`, re-read the v8 regression tests in `tests/validation/test_phase3_v8_fixes.py`, ran the required validation suite, and performed an additional adversarial sweep across every reviewer-facing field.

Required suite run:

```bash
uv run pytest tests/validation/ -v
```

Observed result:
- **96/96 passed**

Note: the task prompt said to expect 97 passing. In the current checkout, pytest collected **96** tests and all passed. I found no failing or skipped validation tests; this appears to be a stale expected count in the task text, not a regression.

## What changed since v8

The remaining v8 blocker was real and is now fixed.

`validation_verdict.criterion_results` is no longer schema-open:
- each entry must be a dict
- each entry is restricted to a strict allowlist:
  - `criterion_id`
  - `verdict`
  - `actual_output`
  - `error`
  - `executed_command`
  - `run_id`
- every populated field in each entry must be a scalar string
- unknown keys such as `details`, `context`, `notes`, etc. are rejected
- nested dict/list payloads inside allowed fields are rejected

That closes the exact smuggling path identified in v8.

## Adversarial attack results

I explicitly probed the remaining candidate reviewer-input smuggling surfaces:

- Top level
  - unknown extra keys
  - direct forbidden builder-private keys
  - non-string `spec`
  - non-string `diffs`
- `criteria[*]`
  - unknown keys
  - dict/list payloads in `criterion_id`, `description`, `criterion_class`
  - nested payloads in `triple.*`
- `artifact_refs[*]`
  - unknown keys
  - dict/list payloads in scalar fields
  - type confusion on `immutable` / `created_at`
- `validation_verdict`
  - unknown keys
  - dict/list payloads in `task_id`, `status`, `reason`
  - non-string items in `must_pass_failures` / `blocked_required`
- `validation_verdict.criterion_results[*]`
  - unknown keys (`details`, `context`, etc.)
  - direct forbidden keys
  - nested dict/list payloads inside allowed fields (`actual_output`, `error`, etc.)
  - clean minimal legitimate entry

Representative outcomes from the direct probes:

- `criterion_results.details = {...}` → rejected as disallowed key
- `criterion_results.context = "..."` → rejected as disallowed key
- `criterion_results.actual_output = {...}` → rejected because allowed fields must be `str`
- `criterion_results.error = [...]` → rejected because allowed fields must be `str`
- `criteria[*].criterion_id = {...}` → rejected because must be `str`
- `criteria[*].triple.verification_command = {...}` → rejected because must be `str`
- `artifact_refs[*].path = {...}` → rejected because scalar-typed
- `validation_verdict.reason = {...}` → rejected because must be `str`
- `validation_verdict.must_pass_failures[0] = {...}` → rejected because items must be `str`
- clean minimal criterion result `{criterion_id, verdict}` → accepted

I did **not** find any remaining reviewer-input smuggling path within the execution-plan scope.

## Blocker table

| # | Blocker | Status | Notes |
|---|---|---|---|
| 1 | Shallow evidence / narrative-only PASS | FIXED | PASS still requires artifact-backed evidence; no regression found. |
| 2 | `BLOCKED` completion semantics | FIXED | Missing/blocked must-pass criteria still prevent completion. |
| 3 | Pass-rate heuristic completion | FIXED | No heuristic completion bypass found. |
| 4 | Verification triple incompleteness not enforced at boundary | FIXED | Malformed triples still fail closed. |
| 5 | Persistence / reload gaps | FIXED | Persistence tests remain green. |
| 6 | Reviewer independence / strict allowlist | FIXED | Reviewer input is allowlisted and structural types are enforced. |
| 7 | Ladder ordering bug | FIXED | No regression found. |
| 8 | Nested forbidden-key injection | FIXED | Nested forbidden-key attempts are rejected along the validated reviewer surface. |
| 9 | Provenance not trusted / self-attestable | FIXED | Registry-backed provenance tests still pass. |
| 10 | Ladder executor missing / fail-fast / resume | FIXED | No regression found. |
| 11 | v4 blocker: `artifact_refs` payload allowlist bypass | FIXED | Artifact refs remain allowlisted and scalar-typed. |
| 12 | v4 blocker: RunRegistry forgeable via artifact substitution | FIXED | Full fingerprint binding still rejects substitution. |
| 13 | v6 blocker: reviewer non-dict list-item smuggling | FIXED | `criteria[*]`, `artifact_refs[*]`, and `validation_verdict` type boundaries hold. |
| 14 | v6 blocker: created_at metadata not bound | FIXED | Binding remains covered by passing tests. |
| 15 | v7 blocker: untyped criterion scalar fields | FIXED | `criterion_id`, `description`, `criterion_class` reject dict/list payloads. |
| 16 | v7/v8 blocker: verdict / `criterion_results` schema openness | FIXED | `reason` is typed, `criterion_results` is now schema-closed and scalar-only. |

## Exact-match legitimate flow

Still preserved.

Evidence:
- full validation suite passed at **96/96**
- clean criterion-result payloads are still accepted by `ReviewerInput.from_raw(...)`
- prior provenance and exact-match regressions remain green, including:
  - `tests/validation/test_phase3_v5_fixes.py::TestFullFingerprintBinding::test_exact_match_still_passes`
  - `tests/validation/test_phase3_v6_fixes.py::TestCreatedAtBinding::test_exact_match_still_accepted`
  - `tests/validation/test_phase3_v4_fixes.py::TestRegistryHashBinding::test_legitimate_artifact_still_accepted`

## Final signoff recommendation

**PASS — sign off Phase 3.**

Within the scope of this adversarial review series, I do not see a remaining reviewer-input smuggling path.

The final v8 gap is closed by making `validation_verdict.criterion_results` fail-closed via:
- strict key allowlisting
- scalar-string enforcement for every field
- continued rejection of non-dict/non-list structural smuggling attempts elsewhere in reviewer input

I would approve this phase as trust-boundary-complete for the reviewed attack surface.
