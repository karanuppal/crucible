# Adversarial Review — Phase 3 Validation and Review Foundation (v8)

Verdict: FAIL

## Summary

I re-read the prior v7 review at `docs/validation/phase-3/adversarial-review-v7.md`, re-reviewed the current reviewer-boundary implementation in `src/agentic_harness/validation/reviewer.py`, inspected adjacent validation/persistence code, re-read the v7 regression tests, and ran the required suite:

```bash
uv run pytest tests/validation/ -v
```

Result:
- **90/90 passed**

The v7-targeted fixes are real:
- `criteria[*].criterion_id` / `description` / `criterion_class` are now type-enforced as strings
- `validation_verdict.task_id` / `status` / `reason` are now type-enforced as strings
- `must_pass_failures` / `blocked_required` are now enforced as list-of-string
- `criterion_results` must now be a list of dicts
- recursive forbidden-key scanning now catches nested builder-private keys inside `criterion_results`
- exact-match legitimate provenance flow still passes

However, I do **not** consider the reviewer trust boundary fully closed yet.

There is still one remaining smuggling surface: `validation_verdict.criterion_results` is still **schema-open**. It rejects known forbidden keys recursively, but it still accepts arbitrary nested dict/list payloads under non-forbidden names. That means builder-originated framing can still cross the reviewer boundary if it is renamed to an innocuous key such as `details`, `context`, `notes`, etc. This is weaker than the rest of the reviewer input contract, which is otherwise fail-closed and allowlisted.

Representative fresh probe:

```python
ReviewerInput.from_raw({
    "spec": "x",
    "criteria": [],
    "validation_verdict": {
        "task_id": "t1",
        "status": "complete",
        "must_pass_failures": [],
        "blocked_required": [],
        "reason": "ok",
        "criterion_results": [{
            "criterion_id": "c1",
            "details": {
                "opaque": ["anything", {"not_forbidden": "secret framing"}]
            },
        }],
    },
})
# ACCEPTED
```

If the security bar is only “block these exact forbidden key names,” then the current implementation passes that bar. But the ask for this pass was stricter than that: **trust-boundary-complete**. A schema-open `criterion_results` object does not meet that bar.

So this remains a **FAIL**.

## Blocker table

| # | Blocker | Status | Notes |
|---|---|---|---|
| 1 | Shallow evidence / narrative-only PASS | FIXED | PASS still requires real artifact-backed evidence. |
| 2 | `BLOCKED` completion semantics | FIXED | Missing/blocked must-pass criteria still prevent completion. |
| 3 | Pass-rate heuristic completion | FIXED | Gate semantics remain intact; no heuristic completion path found. |
| 4 | Verification triple incompleteness not enforced at boundary | FIXED | Malformed triples still fail closed. |
| 5 | Persistence / reload gaps | FIXED | No regression found; persistence tests remain green. |
| 6 | Reviewer independence / strict allowlist | STILL BLOCKING | `criterion_results` remains schema-open; arbitrary nested payloads can still pass under non-forbidden names. |
| 7 | Ladder ordering bug | FIXED | No regression found. |
| 8 | Nested forbidden-key injection | FIXED | Recursive forbidden-key scanning now catches nested builder-private keys, including inside `criterion_results`. |
| 9 | Provenance not trusted / self-attestable | FIXED | Registry-backed provenance still rejects unregistered / wrong-command / wrong-run / tampered evidence. |
| 10 | Ladder executor missing / fail-fast / resume | FIXED | No regression found. |
| 11 | v4 blocker: `artifact_refs` payload allowlist bypass | FIXED | Artifact refs remain allowlisted and scalar-typed. |
| 12 | v4 blocker: RunRegistry forgeable via artifact substitution | FIXED | Full fingerprint binding still rejects substitution by path/type/immutable/hash mismatch. |
| 13 | v6 blocker: reviewer non-dict list-item smuggling | FIXED | `criteria[*]` / `artifact_refs[*]` must be dicts; `validation_verdict` must be a dict. |
| 14 | v6 blocker: created_at metadata not bound | FIXED | `created_at` remains bound in registry verification. |
| 15 | v7 blocker: untyped criterion scalar fields | FIXED | `criterion_id`, `description`, `criterion_class` now reject dict/list payloads. |
| 16 | v7 blocker: untyped verdict reason / criterion_results | STILL BLOCKING | `reason` is fixed, but `criterion_results` is still only blacklist-scanned, not schema-closed. |

## Exact-match legitimate flow

Still works.

Evidence:
- full suite passed at **90/90**
- existing exact-match provenance regressions still pass:
  - `tests/validation/test_phase3_v5_fixes.py::TestFullFingerprintBinding::test_exact_match_still_passes`
  - `tests/validation/test_phase3_v6_fixes.py::TestCreatedAtBinding::test_exact_match_still_accepted`
  - `tests/validation/test_phase3_v4_fixes.py::TestRegistryHashBinding::test_legitimate_artifact_still_accepted`

## Signoff recommendation

**Do not sign off Phase 3 yet.**

One more tightening pass is needed:
- either remove `validation_verdict.criterion_results` from reviewer input entirely, or
- define its exact allowed schema and validate it recursively allowlist-first

Until `criterion_results` is schema-closed, the reviewer boundary is not genuinely fail-closed, and I would not call it trust-boundary-complete.
