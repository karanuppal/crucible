# Adversarial Review — Phase 3 Validation and Review Foundation (v5)

Verdict: FAIL

## Summary

I re-read:
- `docs/validation/phase-3/adversarial-review-v4.md`
- Phase 3 source under `src/agentic_harness/validation/*.py`
- Phase 3 tests under `tests/validation/*.py` (especially `test_phase3_v4_fixes.py`)
- `EXECUTION_PLAN.md` Phase 3 section

I also ran the required test command:
- `uv run pytest tests/validation/ -v`
- Result: **65/65 passed**

However, Phase 3 is **still not signoff-ready**.

The two v4 blockers were only partially fixed. The obvious versions are covered by tests, but stricter adversarial attacks still break both trust boundaries:

1. **Reviewer allowlist can still be bypassed via nested payloads inside allowed `artifact_refs` fields**
2. **RunRegistry provenance can still be forged via same-`artifact_id`, same-hash substituted artifact objects**

Those remain blocking under the Phase 3 execution-plan standard.

---

## Full blocker table (12 total)

| # | Blocker | Status | Notes |
|---|---|---|---|
| 1 | Shallow evidence / narrative-only PASS | FIXED | `Validator` downgrades PASS without real artifact-backed evidence. |
| 2 | `BLOCKED` completion semantics | FIXED | Missing/blocked must-pass criteria keep verdict incomplete. |
| 3 | Pass-rate heuristic completion | FIXED | Gate-based completion logic remains in place; no pass-rate shortcut. |
| 4 | Verification triple incompleteness not enforced at boundary | FIXED | Validator fails closed when any criterion triple is malformed. |
| 5 | Persistence / reload gaps | FIXED | Validation state, ladder state, and run registry are persisted and reload correctly for the reviewed scenarios. |
| 6 | Reviewer independence / strict allowlist | **BLOCKING** | Superficially improved, but still bypassable through nested typed payloads inside allowed `artifact_refs` fields. |
| 7 | Ladder ordering bug | FIXED | `LadderRung` uses `IntEnum`; ordering is correct. |
| 8 | Nested forbidden-key injection | **PARTIALLY FIXED / STILL BLOCKING VIA ARTIFACT_REFS VALUES** | Nested forbidden keys are blocked in checked dicts, but not inside values of allowed `artifact_refs` keys because types are not enforced recursively. |
| 9 | Provenance not trusted / self-attestable | **BLOCKING** | Registry now binds `artifact_id -> content_hash`, but not full artifact identity. Same-hash substitution still passes. |
| 10 | Ladder executor missing / fail-fast / resume | FIXED | Executor exists; fail-fast and resume behavior look correct. |
| 11 | v4 blocker: `artifact_refs` payload allowlist bypass | **BLOCKING** | Simple top-level extra-key version is fixed, but nested dict smuggling still works. |
| 12 | v4 blocker: RunRegistry forgeable via artifact substitution | **BLOCKING** | Different-content substitution is fixed; same-hash substituted artifact object still passes. |

---

## What I verified

### Test suite
Command run:

```bash
uv run pytest tests/validation/ -v
```

Result:
- **65 passed in 0.04s**

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

### 1) `artifact_refs` still allows nested builder-private payloads via allowed fields
**Blocking**

`reviewer.py` now allowlists top-level `artifact_refs[*]` keys:
- `artifact_id`
- `type`
- `path`
- `content_hash`
- `producer_run_id`
- `created_at`
- `immutable`

But it does **not** validate the **types** of those fields, and it does **not** recurse into values of allowed keys.

That means a payload like this is still accepted:

```python
raw = {
    "spec": "x",
    "criteria": [],
    "artifact_refs": [{
        "artifact_id": "a1",
        "type": "log",
        "path": {"builder_rationale": "secret"},
        "content_hash": "xx",
        "producer_run_id": "r1",
        "created_at": 0.0,
        "immutable": True,
    }],
}
ReviewerInput.from_raw(raw)  # accepted
```

Observed result:
- **accepted successfully** (`BYPASS_ACCEPTED`)

Why this matters:
- the reviewer boundary is still not a strict schema boundary
- builder-private material can be smuggled inside a nominally allowed field
- the current tests only cover extra top-level keys on `artifact_refs` entries, not nested typed payloads under allowed keys

Root cause:
- `validate_reviewer_input()` only applies `_strict_allowlist_check()` to each `artifact_refs` dict itself
- it never type-checks `path`, `content_hash`, `artifact_id`, etc. as scalars
- it never normalizes/constructs `ArtifactRef` objects during validation

Conclusion:
- blocker #6 / #11 is **not actually closed**

---

### 2) RunRegistry provenance is still forgeable with same-hash substituted artifact objects
**Blocking**

`run_registry.py` is improved versus v4. It now checks:
1. run exists
2. command matches expected command
3. artifact ID is listed on the run
4. submitted artifact hash matches recorded hash for that artifact ID
5. submitted file still verifies against that hash

That blocks the obvious “same ID, different content” attack.

But it still does **not** bind artifact identity to:
- original path
- original type
- original immutability flag
- original creation time
- a registry-owned immutable artifact record

Fresh attack:
- register run with artifact A (`artifact_id="art-shared"`, type `LOG`, path `good.log`)
- create artifact B with:
  - same `artifact_id`
  - same file contents / same hash
  - **different path**
  - **different type**
  - **different `immutable` value**
- submit artifact B as PASS evidence with the recorded run ID

Observed result:
- `registry.verify_provenance(...) == True`
- validator returned **`complete`**

Concrete attack shape:

```python
art1 = create_artifact_ref("good.log", ArtifactType.LOG, "placeholder", artifact_id="art-shared")
record = registry.record_run(..., artifacts=[art1])

art2 = ArtifactRef(
    artifact_id="art-shared",
    type=ArtifactType.DIFF,      # changed
    path="copied.log",          # changed
    content_hash=art1.content_hash,  # same hash
    producer_run_id=record.run_id,
    created_at=time.time() + 1000,   # changed
    immutable=False,             # changed
)

# validator accepts this forged evidence
```

Why this matters:
- the registry still trusts a caller-supplied artifact object rather than an authoritative stored artifact record
- provenance is still based on partial identity (`artifact_id + hash`) instead of full artifact identity
- an attacker can substitute a different object and still satisfy the registry check as long as bytes match

This is not just cosmetic:
- `ArtifactRef` is supposed to be a durable typed pointer, not merely “some file with the same bytes somewhere else”
- the execution plan requires trustable evidence linkage, not caller-swappable evidence wrappers

Conclusion:
- blocker #9 / #12 is **not actually closed**

---

## Requested attack answers

### 1) Can a forbidden key still sneak into `artifact_refs`?
**Yes.**

Not by adding an extra top-level key to the `artifact_refs` item anymore; that part is fixed.

But a forbidden key can still be smuggled by placing a nested dict under an allowed field such as `path`:

```python
"path": {"builder_rationale": "secret"}
```

Because field types are not enforced and nested values are not recursively checked, this bypass is still live.

### 2) Can RunRegistry still be forged with same `artifact_id`?
**Yes.**

The “same ID, different content hash” attack is fixed.

But a stronger forged artifact still works if it reuses:
- the same `artifact_id`
- the same content hash
- the same run ID

while changing other identity-bearing fields like path/type/immutability/created_at.

That still produces a valid-looking, registry-accepted substitute artifact object.

### 3) Is `diffs` locked down?
**Mostly yes for the specific structural-smuggling concern.**

`reviewer.py` now enforces:
- `diffs` must be a plain string
- dict/list payloads are rejected

So the obvious structured-smuggling path through `diffs` is closed.

Caveat:
- `diffs` is still arbitrary reviewer-visible text by design, so this is not a builder-private boundary; it is only structurally constrained, not semantically sanitized

I do **not** consider `diffs` a current blocker.

### 4) Any other sneak paths?
**No new equally severe blocker found beyond the two above.**

Other reviewed areas look materially improved:
- fail-closed triple enforcement is real
- anti-vacuity remains in place
- ladder execution semantics look correct
- persistence/reload paths are present and covered better than before

But the two remaining trust-boundary bugs are enough to keep Phase 3 at FAIL.

---

## Why the green test suite is not enough

The current suite proves the implementation blocks the **known simple versions** of the two v4 attacks.

It does **not** prove the boundary is actually closed, because it missed:
- nested typed payloads inside allowed `artifact_refs` fields
- same-hash substituted artifacts with mutated path/type/immutability metadata

So the test suite is now stronger, but still not sufficient for final signoff.

---

## Minimum fixes required before PASS

1. **Make reviewer input truly schema-strict for `artifact_refs`**
   - validate field types, not just keys
   - reject non-scalar payloads for scalar fields
   - preferably parse/normalize each entry with `ArtifactRef.from_dict()` (or equivalent strict constructor) during reviewer-input validation
   - add explicit regression tests for nested dict injection under each allowed field

2. **Make RunRegistry authoritative over full artifact identity, not just ID+hash**
   - store immutable registry-owned artifact records, not just `artifact_ids` and `artifact_hashes`
   - provenance check should compare the submitted artifact against the full stored record, or better yet return/use the stored artifact record directly
   - at minimum bind and verify:
     - `artifact_id`
     - `type`
     - `path` (or a deliberate canonical location / registry-owned copy)
     - `content_hash`
     - `producer_run_id`
     - immutability expectations
   - if path should not be trusted, then the registry must own the artifact blob/copy rather than trusting caller-supplied paths

3. **Add regression tests for the real attacks**
   - nested dict in `artifact_refs.path`
   - nested dict in other scalar `artifact_refs` fields
   - same-hash substituted artifact object with changed path/type/immutability

---

## Final signoff recommendation

**Do not sign off Phase 3.**

Recommendation:
- keep Phase 3 at **FAIL**
- fix the two remaining trust-boundary issues above
- add explicit regression tests for both
- rerun adversarial review after those fixes

A PASS here would overstate the actual security/trust properties of the validation foundation. The code is close, and much better than earlier passes, but it is **not yet ready to ship as signed-off foundation code**.
