# Adversarial Review — Phase 3 Validation and Review Foundation (v7)

Verdict: FAIL

## Summary

I re-read the prior v6 review at `docs/validation/phase-3/adversarial-review-v6.md`, re-reviewed the current Phase 3 validation source under `src/agentic_harness/validation/*.py`, re-read the validation tests under `tests/validation/*.py`, and ran the required suite:

```bash
uv run pytest tests/validation/ -v
```

Result:
- **81/81 passed**

The v6-targeted fixes are real and effective:
- non-dict list items in `criteria` / `artifact_refs` are now rejected
- `validation_verdict` must now be a dict
- `RunRegistry` now binds `created_at`
- `RunRegistry.record_run()` stamps `producer_run_id` onto artifacts before fingerprinting
- exact-match legitimate provenance still works

However, Phase 3 is **still not signoff-ready**.

I found a new remaining reviewer-input smuggling path: several fields that are treated as scalar/logical metadata are still not type-enforced, so nested dict payloads containing builder-private framing can still cross the reviewer boundary. In contrast, I did **not** find a remaining registry metadata forgery bypass after the v6 changes.

Bottom line:
- **Reviewer-input trust boundary is still not fully closed**
- **Registry provenance binding now appears closed for the reviewed metadata surface**
- **Legitimate exact-match flow still works**

So the overall verdict remains **FAIL**.

---

## Status of all 14 blockers

| # | Blocker | Status | Notes |
|---|---|---|---|
| 1 | Shallow evidence / narrative-only PASS | FIXED | Validator still downgrades PASS without artifact-backed evidence. |
| 2 | `BLOCKED` completion semantics | FIXED | Missing/blocked must-pass criteria still prevent completion. |
| 3 | Pass-rate heuristic completion | FIXED | Gate-based completion remains intact. |
| 4 | Verification triple incompleteness not enforced at boundary | FIXED | Validator still fails closed on malformed triples. |
| 5 | Persistence / reload gaps | FIXED | No regression found; persistence tests pass. |
| 6 | Reviewer independence / strict allowlist | **STILL BLOCKING** | Outer allowlists exist, but nested dict payloads still pass through some untyped allowed fields. |
| 7 | Ladder ordering bug | FIXED | No regression found. |
| 8 | Nested forbidden-key injection | **STILL BLOCKING** | Previously found list-item path is fixed, but new nested-data paths remain via untyped criterion/verdict fields. |
| 9 | Provenance not trusted / self-attestable | FIXED | Registry-backed provenance still blocks unregistered/wrong-command/wrong-run/tampered evidence. |
| 10 | Ladder executor missing / fail-fast / resume | FIXED | No regression found in source/tests. |
| 11 | v4 blocker: `artifact_refs` payload allowlist bypass | FIXED | `artifact_refs` dicts are allowlisted and non-dict list items are rejected. |
| 12 | v4 blocker: RunRegistry forgeable via artifact substitution | FIXED | Full fingerprint binding still rejects substitution by path/type/immutable/hash mismatch. |
| 13 | v6 blocker: reviewer non-dict list-item smuggling | FIXED | `criteria[*]` / `artifact_refs[*]` must now be dicts; `validation_verdict` must be dict. |
| 14 | v6 blocker: created_at metadata not bound | FIXED | `created_at` is now included in registry fingerprint and enforced at provenance check. |

---

## Fresh adversarial findings

### 1) Reviewer input can still smuggle nested builder-framing through untyped criterion fields
**Blocking**

The v6 fix correctly enforced that `criteria` must be a list of dicts. But inside each criterion dict, the code only:
- allowlists the keys
- type-checks `triple`
- type-checks fields inside `triple`

It does **not** type-check these criterion-level fields:
- `criterion_id`
- `description`
- `criterion_class`

That means nested dict payloads can still be placed inside those fields and pass validation unchanged.

Concrete probes I ran:

```python
ReviewerInput.from_raw({
    "spec": "x",
    "criteria": [{
        "criterion_id": {"builder_rationale": "secret"},
        "description": "d",
        "criterion_class": "must_pass",
        "triple": {
            "build_target": "src/foo.py",
            "verification_command": "pytest tests/foo.py",
            "expected_output": "PASSED",
            "failure_signature": "FAILED",
        },
    }],
})
# ACCEPTED
```

```python
ReviewerInput.from_raw({
    "spec": "x",
    "criteria": [{
        "criterion_id": "c1",
        "description": {"builder_rationale": "secret"},
        "criterion_class": "must_pass",
        "triple": {
            "build_target": "src/foo.py",
            "verification_command": "pytest tests/foo.py",
            "expected_output": "PASSED",
            "failure_signature": "FAILED",
        },
    }],
})
# ACCEPTED
```

```python
ReviewerInput.from_raw({
    "spec": "x",
    "criteria": [{
        "criterion_id": "c1",
        "description": "d",
        "criterion_class": {"builder_rationale": "secret"},
        "triple": {
            "build_target": "src/foo.py",
            "verification_command": "pytest tests/foo.py",
            "expected_output": "PASSED",
            "failure_signature": "FAILED",
        },
    }],
})
# ACCEPTED
```

Why this matters:
- the reviewer boundary is still not fail-closed on structure
- nested/private builder framing can still cross into reviewer-visible input
- the old v6 bypass is fixed, but the broader issue remains: some allowed fields are only key-checked, not type-checked

Conclusion:
- **Question 1: Any remaining reviewer-input smuggling path?**
- **Yes. Still blocking.**

---

### 2) Reviewer input can still smuggle nested payloads through untyped `validation_verdict` subfields
**Blocking**

`validation_verdict` is now enforced to be a dict, which fixes the v6 list-shaped bypass. But the validator only allowlists its top-level keys. It does **not** recursively validate or structurally type-check several values inside that dict.

In particular:
- `reason` is not enforced to be a string
- `criterion_results` is not enforced to be a list of safe scalar/known-shape items
- list contents inside `criterion_results` are not recursively checked at all

Concrete probes I ran:

```python
ReviewerInput.from_raw({
    "spec": "x",
    "criteria": [],
    "validation_verdict": {
        "task_id": "t1",
        "status": "complete",
        "must_pass_failures": [],
        "blocked_required": [],
        "reason": {"builder_rationale": "secret"},
        "criterion_results": [],
    },
})
# ACCEPTED
```

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
        "criterion_results": [{"builder_rationale": "secret"}],
    },
})
# ACCEPTED
```

Why this matters:
- this is still reviewer-input smuggling through an allowed top-level field
- the object is not schema-closed past the first dict layer
- builder-private framing can still be nested inside verdict content

Conclusion:
- **Question 1: Any remaining reviewer-input smuggling path?**
- **Yes. Still blocking.**

---

### 3) Registry metadata forgery: no remaining bypass found in reviewed surface
**Fixed**

I re-checked the exact v6 target area and additional nearby metadata:
- exact match => accepted
- mutated `producer_run_id` => rejected
- mutated `created_at` => rejected
- mutated `path` => rejected
- mutated `immutable` => rejected

Representative probe results:

```text
[OK] exact match provenance: 'complete'
[OK] mutated producer_run_id rejected: 'incomplete'
[OK] mutated created_at rejected: 'incomplete'
[OK] mutated path rejected: 'incomplete'
[OK] mutated immutable rejected: 'incomplete'
```

I did not find a remaining registry metadata-forgery path within the artifact fingerprint fields the registry now treats as authoritative.

Conclusion:
- **Question 2: Any remaining registry metadata forgery?**
- **Not found in this pass. Consider this fixed for the reviewed trust surface.**

---

### 4) Exact-match legitimate flow still works
**Passes**

I verified both via the test suite and targeted probes that the legitimate control still succeeds:
- real artifact
- recorded run
- registry-stamped `producer_run_id`
- exact metadata match
- intact file integrity

Observed result:
- validator verdict = `COMPLETE`

Conclusion:
- **Question 3: Does exact-match legitimate flow still work?**
- **Yes.**

---

## Required fixes before PASS

To make reviewer input genuinely trust-boundary-safe, Phase 3 still needs one more fail-closed tightening pass:

1. **Type-enforce criterion fields**
   - `criterion_id` must be `str`
   - `description` must be `str`
   - `criterion_class` must be `str` (or normalized enum-compatible scalar)
   - reject dict/list payloads in all of them

2. **Type-enforce / schema-close `validation_verdict` subfields**
   - `task_id`, `status`, `reason` must be strings
   - `must_pass_failures`, `blocked_required` must be lists of strings
   - `criterion_results` must either:
     - be omitted from reviewer input, or
     - be fully schema-defined and recursively validated
   - if retaining `criterion_results`, reject arbitrary dict/list payloads and validate every nested item shape

3. **Add regressions for the newly found smuggling paths**
   - `criteria[0].criterion_id = {"builder_rationale": "secret"}`
   - `criteria[0].description = {"builder_rationale": "secret"}`
   - `criteria[0].criterion_class = {"builder_rationale": "secret"}`
   - `validation_verdict.reason = {"builder_rationale": "secret"}`
   - `validation_verdict.criterion_results = [{"builder_rationale": "secret"}]`

---

## Final recommendation

**Recommendation: FAIL. Do not sign off Phase 3 yet.**

Strict but fair summary:
- the v6 fixes are real
- the registry/provenance side now looks materially solid
- exact-match legitimate flow still works
- the full validation suite is green at **81/81**

But the reviewer boundary is still not actually closed. Nested builder-private data can still cross through untyped allowed fields inside `criteria` and `validation_verdict`.

That means this is **not yet ready to ship as signed-off foundation code with no remaining trust-boundary issues**.

If the remaining reviewer-field typing/schema-closure issues are fixed and covered by regressions, the next pass could plausibly be the first real PASS candidate.
