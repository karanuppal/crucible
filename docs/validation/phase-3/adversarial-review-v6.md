# Adversarial Review — Phase 3 Validation and Review Foundation (v6)

Verdict: FAIL

## Summary

I re-read all prior adversarial reviews in `docs/validation/phase-3/`:
- `adversarial-review.md` (original / v1)
- `adversarial-review-v2.md`
- `adversarial-review-v3.md`
- `adversarial-review-v4.md`
- `adversarial-review-v5.md`

I also re-read the current Phase 3 source under `src/agentic_harness/validation/*.py`, the validation tests under `tests/validation/*.py`, and ran the required test command:

```bash
uv run pytest tests/validation/ -v
```

Result:
- **73/73 passed**

However, this is still **not signoff-ready**.

The two v5 target fixes are improved, but both remain bypassable under stricter adversarial probing:

1. **Reviewer input is still not truly schema-closed** — nested data can still be smuggled through allowed list-valued fields by using non-dict items.
2. **RunRegistry provenance is still not fully bound against metadata variation** — mutating `created_at` still passes provenance and produces a COMPLETE validator verdict.

Exact-match legitimate provenance does still work, but the remaining trust-boundary holes keep the verdict at **FAIL**.

---

## Status of all 12 prior blockers

| # | Blocker | Status | Notes |
|---|---|---|---|
| 1 | Shallow evidence / narrative-only PASS | FIXED | Validator still downgrades PASS without artifact-backed evidence. |
| 2 | `BLOCKED` completion semantics | FIXED | Missing/blocked must-pass criteria still keep the verdict incomplete. |
| 3 | Pass-rate heuristic completion | FIXED | Gate-based completion logic remains in place. |
| 4 | Verification triple incompleteness not enforced at boundary | FIXED | Validator still fails closed on malformed triples. |
| 5 | Persistence / reload gaps | FIXED | Reviewed persistence paths and tests remain in place for the scoped Phase 3 state. |
| 6 | Reviewer independence / strict allowlist | **BLOCKING** | v5 scalar-type fix closes dict-inside-scalar attacks, but allowed list fields still accept non-dict nested payloads. |
| 7 | Ladder ordering bug | FIXED | Numeric ordering remains correct. |
| 8 | Nested forbidden-key injection | **PARTIALLY FIXED / STILL BLOCKING** | Nested forbidden keys inside checked dicts are blocked, but nested data can still enter through non-dict list entries. |
| 9 | Provenance not trusted / self-attestable | **BLOCKING** | Full fingerprint binding for path/type/immutable is better, but provenance still accepts metadata variation in `created_at`. |
| 10 | Ladder executor missing / fail-fast / resume | FIXED | No regression found in reviewed code/tests. |
| 11 | v4 blocker: `artifact_refs` payload allowlist bypass | **BLOCKING** | Old scalar-field dict-smuggling path is fixed, but list-item smuggling still works. |
| 12 | v4 blocker: RunRegistry forgeable via artifact substitution | **BLOCKING** | Same-id + same-hash + same-path/type/immutable now fails appropriately when those differ, but metadata variation via `created_at` still passes. |

---

## Fresh adversarial findings

### 1) Reviewer input still accepts nested data through non-dict items in allowed list fields
**Blocking**

The v5 fix added scalar typing for dict-shaped `artifact_refs[*]` entries. That closes the specific attack from v5:

```python
{"path": {"builder_rationale": "secret"}}
```

But `validate_reviewer_input()` only validates list entries **if they are dicts**:
- `criteria[*]` checked only when `isinstance(c, dict)`
- `artifact_refs[*]` checked only when `isinstance(ar, dict)`
- `validation_verdict` checked only when it is a dict

That leaves an end-run: put nested data into an allowed field as a **non-dict list item** and it is accepted wholesale.

Concrete probes I ran:

```python
ReviewerInput.from_raw({
    "spec": "x",
    "criteria": [],
    "artifact_refs": [["secret"]],
    "validation_verdict": {},
    "diffs": "",
})
# ACCEPTED
```

```python
ReviewerInput.from_raw({
    "spec": "x",
    "criteria": [["secret"]],
    "artifact_refs": [],
    "validation_verdict": {},
    "diffs": "",
})
# ACCEPTED
```

```python
ReviewerInput.from_raw({
    "spec": "x",
    "criteria": [],
    "artifact_refs": [],
    "validation_verdict": [{"builder_rationale": "secret"}],
    "diffs": "",
})
# ACCEPTED
```

Why this matters:
- reviewer input is still not a true strict schema boundary
- nested/private framing can still enter reviewer-visible input via allowed fields
- the v5 fix closed one structural path, but not the broader “only validate dicts, ignore everything else” hole

Root cause:
- allowlist/type validation is conditional on entries already being dicts
- there is no fail-closed type enforcement that `criteria` must be list[dict], `artifact_refs` must be list[dict or ArtifactRef], and `validation_verdict` must be dict

Conclusion:
- **Question 1: Can you still smuggle nested data into reviewer input via any allowed field?**
- **Yes.**

---

### 2) RunRegistry still allows provenance under metadata variation (`created_at`)
**Blocking**

The v5 fix materially improved registry binding. I re-tested the exact class of prior attacks:
- same `artifact_id`
- same `content_hash`
- different `path` → rejected
- different `type` → rejected
- different `immutable` → rejected
- exact match → accepted

That part is real.

But the current registry fingerprint does **not** bind `created_at`, and `verify_provenance()` ignores it entirely.

Concrete probe I ran:
- register a real artifact
- submit a second `ArtifactRef` with the same:
  - `artifact_id`
  - `path`
  - `type`
  - `content_hash`
  - `immutable`
  - `producer_run_id`
- but a **different `created_at`**

Observed result:

```python
verify_provenance == True
validator verdict == COMPLETE
```

So provenance still succeeds under a metadata variation.

Why this matters:
- the task prompt asked whether provenance can still be forged with **any metadata variation**
- earlier reviews explicitly treated `created_at` as part of artifact identity metadata worth defending
- a caller can still submit a non-identical artifact object and have it treated as authoritative provenance

This is weaker than the pre-v5 hole, but it is still a trust-boundary gap.

Conclusion:
- **Question 2: Can you still forge registry provenance with any metadata variation?**
- **Yes — `created_at` can still vary without invalidating provenance.**

---

### 3) Exact-match legitimate provenance still works
**Passes**

I confirmed the positive control remains good:
- same command
- same registered run
- same artifact object / exact metadata match
- integrity intact

Observed result:
- `verify_provenance(...) == True`
- validator verdict == `COMPLETE`

Conclusion:
- **Question 3: Does exact-match legitimate provenance still work?**
- **Yes.**

---

## Any new findings

### New blocker beyond the literal v5 test cases
The biggest new finding is that the reviewer boundary is still vulnerable not through scalar-field dict smuggling, but through **non-dict list entries** in allowed top-level fields.

This is a real trust-boundary bypass that current tests do not cover.

### Registry finding is narrower but still real
The provenance issue is no longer “path/type/immutable not bound” — that part looks fixed.

The remaining hole is narrower:
- `created_at` remains unbound and can vary without invalidating provenance.

If the intended identity contract is “full artifact object equality except maybe explicitly irrelevant fields,” this is still a blocker.

---

## Minimum fixes required before PASS

1. **Make reviewer input fail closed on container types, not just keys inside dicts**
   - enforce `criteria` is `list[dict]`
   - enforce `artifact_refs` is `list[dict]` or normalize strictly to `ArtifactRef`
   - enforce `validation_verdict` is a dict
   - reject list/scalar payloads where structured dicts are expected
   - add regressions for:
     - `artifact_refs=[[...]]`
     - `criteria=[[...]]`
     - `validation_verdict=[...]`

2. **Decide and enforce whether `created_at` is identity-bearing**
   - if yes: bind it in `RunRegistry.artifact_fingerprints` and compare it in `verify_provenance()`
   - if no: document that explicitly and treat it as non-authoritative metadata everywhere
   - add a regression test either way so the contract is unambiguous

3. **Add regression tests for the discovered paths**
   - reviewer non-dict list item smuggling
   - provenance acceptance/rejection with mutated `created_at`

---

## Final signoff recommendation

**Recommendation: FAIL. Do not sign off Phase 3 yet.**

Strict but fair bottom line:
- the code is clearly much stronger than v4/v5
- the obvious v5 attack shapes are fixed
- exact-match legitimate provenance still works
- the full test suite is green at **73/73**

But the remaining reviewer-input bypass and metadata-variation provenance gap mean the trust boundary is still not genuinely closed.

If the reviewer container typing is tightened and the `created_at` contract is made explicit and enforced, I would expect the next pass to be a credible candidate for final PASS.