# Adversarial Review — Phase 3 Validation and Review Foundation (v4)

Verdict: FAIL

## Summary

I re-read all three prior adversarial reviews, the Phase 3 section of `EXECUTION_PLAN.md`, all Phase 3 source under `src/agentic_harness/validation/`, and all tests under `tests/validation/`.

I also ran the required test command:
- `uv run pytest tests/validation/ -v`
- Result: **58/58 passed**

But Phase 3 is **still not signoff-ready**.

The implementation has clearly improved a lot since v1/v2/v3. Most previously reported issues are now fixed or materially improved. However, fresh adversarial testing still found **two blocking trust-boundary bypasses**:

1. **Reviewer strict allowlist can still be bypassed through `artifact_refs` payload contents**
2. **RunRegistry provenance can still be forged via artifact-ID collision / substituted artifact object**

Those are enough to keep Phase 3 at **FAIL** under the execution plan’s trust standard.

---

## Blocker table (all 10)

| # | Prior blocker | Status | Notes |
|---|---|---|---|
| 1 | Shallow evidence | FIXED | Narrative strings alone no longer pass. Validator requires artifact-backed evidence and downgrades unsupported PASS results. |
| 2 | `BLOCKED` completion | FIXED | Missing/blocked must-pass criteria now keep the verdict incomplete. |
| 3 | Pass-rate verdict | FIXED | Verdict logic is gate-based; pass-rate heuristics are gone. |
| 4 | Triple fields (+ enforcement at boundary) | FIXED | Triple now includes build target / command / expected output / failure signature, and validator enforces well-formed triples fail-closed. |
| 5 | Persistence (+ ladder transcripts + registry) | PASS WITH OBSERVATIONS | Persistence exists for validation state, ladder state, and run registry. Not perfect, but the original blocker is substantially closed. |
| 6 | Reviewer independence (+ strict allowlist) | **BLOCKING REGRESSION** | Recursive allowlist checks exist for `criteria`, `triple`, and `validation_verdict`, but `artifact_refs` contents are not validated. Builder-private material can still be smuggled there. |
| 7 | Ladder ordering | FIXED | `IntEnum` ordering removes the old lexicographic bug. |
| 8 | Nested forbidden keys | FIXED | Nested forbidden-key injection through checked dicts is rejected. |
| 9 | Provenance (+ trusted RunRegistry) | **BLOCKING REGRESSION** | Registry is better than self-attestation, but still trusts artifact ID membership only; forged artifact objects with colliding IDs are accepted. |
| 10 | Ladder executor (rung-by-rung, fail-fast, resume) | FIXED | Real executor exists. Fresh testing shows fail-fast works and `resume()` re-executes the failed rung rather than skipping it. |

---

## What I verified

### Tests
- Ran `uv run pytest tests/validation/ -v`
- Result: **58 passed**

### Source areas reviewed
- `artifact.py`
- `criterion.py`
- `validator.py`
- `reviewer.py`
- `run_registry.py`
- `ladder.py`
- `ladder_executor.py`
- `persistence.py`
- `anti_vacuity.py`
- all files under `tests/validation/`

---

## Fresh adversarial findings

### 1) Reviewer allowlist still bypassable through `artifact_refs`
**Blocking**

`reviewer.py` advertises a strict allowlist, but in practice it only enforces nested structure for:
- top-level reviewer input
- `criteria[*]`
- `criteria[*].triple`
- `validation_verdict`

It does **not** validate the shape of `artifact_refs` entries.

Fresh attack used:

```python
raw = {
  "spec": "x",
  "criteria": [],
  "artifact_refs": [{
    "artifact_id": "a1",
    "type": "log",
    "path": "/tmp/x",
    "content_hash": "h",
    "producer_run_id": "r1",
    "created_at": 0,
    "builder_rationale": "secret"
  }],
  "validation_verdict": {},
  "diffs": "",
}
ReviewerInput.from_raw(raw)
```

Observed result:
- accepted successfully (`BYPASS_OK`)

Impact:
- reviewer isolation is still not a true strict-contract boundary
- builder-private framing can still be passed to the reviewer in an allowed top-level field
- this directly undermines blocker #6 despite the new allowlist language and tests

Root cause:
- `validate_reviewer_input()` never applies nested allowlist validation to `artifact_refs`

---

### 2) RunRegistry provenance still forgeable via artifact-ID collision / substituted artifact object
**Blocking**

The validator now consults `RunRegistry`, which is a real improvement. But the registry currently verifies only:
1. run exists
2. command matches expected command
3. artifact ID appears in `record.artifact_ids`

It does **not** bind the registered artifact ID to:
- artifact path
- artifact hash
- artifact type
- artifact creation time
- a registry-owned immutable artifact record

Fresh attack:
- register a run with artifact ID `art-shared`
- create a **different** artifact object pointing at a different file, but reuse the same `artifact_id="art-shared"`
- set its `producer_run_id` to the recorded run
- submit it as evidence

Observed result:
- validator returned `complete`
- reason: `All must-pass criteria PASS with verified artifacts`

Why this works:
- local evidence validation checks only the submitted artifact object’s own path/hash consistency
- registry validation checks only whether the submitted artifact ID is listed on the run
- there is no authoritative registry-side artifact record to prove the submitted artifact object is the same artifact that the run actually produced

Impact:
- provenance is still consistency-checked, not fully trusted
- a caller can swap in a different artifact while preserving a listed artifact ID
- this keeps blocker #9 open at signoff level

---

## Requested attack answers

### Can allowlist still be bypassed?
**Yes.**

Not through the previously tested `criteria` / `triple` / `validation_verdict` nested dict paths, but through unvalidated `artifact_refs` contents. The strict allowlist is not yet truly end-to-end.

### Can RunRegistry be tricked (e.g., via shared state)?
**Yes.**

The simplest concrete path is artifact-ID collision / artifact substitution:
- registry trusts artifact ID membership only
- validator trusts the caller-supplied artifact object for path/hash
- those two checks are not tied to the same authoritative stored artifact record

So provenance can still be forged by submitting a different artifact object that reuses a registered artifact ID.

### Is ladder executor fail-fast reliable?
**Yes, based on current code and fresh execution.**

I verified:
- a failing rung stops later rungs from executing
- later rungs do not mask failure

This blocker appears closed.

### Does resume correctly re-execute failed rung?
**Yes.**

Fresh execution showed:
- initial run failed at `UNIT`
- `resume()` restarted at `UNIT`
- after the rerun passed, execution continued to later rungs

This blocker appears closed.

---

## Additional observations

### Persistence is much better than before
This is no longer the empty hole seen in earlier reviews. There is now durable state for verdicts, reviewer reports, ladder state, and run registry. I would not block Phase 3 solely on persistence anymore.

### Test suite quality improved, but still missed the two fresh boundary attacks
The current 58 tests are meaningful and cover many earlier gaps. But they do not currently include:
- nested/structured validation of `artifact_refs` in reviewer input
- registry-side rejection of substituted artifacts that reuse a valid artifact ID

Those should be added before claiming signoff.

---

## Signoff recommendation

**Do not sign off Phase 3.**

Minimum required fixes before PASS:

1. **Close reviewer allowlist fully**
   - apply strict schema/allowlist validation to `artifact_refs` entries too
   - ideally normalize them to real `ArtifactRef` objects before reviewer exposure

2. **Make RunRegistry authoritative over artifact identity, not just artifact ID membership**
   - registry should store immutable artifact metadata per artifact ID
   - provenance check should verify submitted artifact matches registry-stored path/hash/type/run binding
   - artifact ID reuse with different content/path must fail

3. **Add explicit regression tests for both attacks**
   - reviewer-input bypass via `artifact_refs`
   - registry provenance bypass via substituted artifact object / colliding artifact ID

Until those are fixed, a PASS verdict would overstate the actual trust boundary.
