# Phase 6 Adversarial Review — Second Pass

Verdict: PASS

## Summary

I re-ran the Phase 6 accelerator test suite and then attacked the two prior blockers plus a few adjacent edge cases.

Executed evidence:
- `uv run pytest tests/accelerators/ -v` → 23/23 passing
- Additional adversarial probes run with `PYTHONPATH=src uv run python ...`

The two v1 blockers are fixed:
- Capability over-claim is now rejected by `verify_observed_behavior()` when a required capability was declared but not actually delivered (`src/agentic_harness/accelerators/capabilities.py:68-101`)
- Router state is now persisted on each mutation path that matters for restart safety, including attempted backend tracking and failover event creation (`src/agentic_harness/accelerators/router.py:121-126, 133-140, 157-165`)

## Blocker table

| Item | Prior status | v2 result | Evidence | Blocker now? |
|---|---|---|---|---|
| Capability over-claim not detected | FAIL | FIXED | Over-claim check added in `verify_observed_behavior()` (`capabilities.py:95-100`); covered by `tests/accelerators/test_phase6_v2_fixes.py:21-47`; adversarial repro raised `CapabilityMismatchError` as expected | No |
| Router state not persisted on every mutation | FAIL | FIXED | `_save()` now happens after attempted-set mutation and after failover mutation (`router.py:125-126, 139, 165`); covered by `tests/accelerators/test_phase6_v2_fixes.py:54-99`; restart probe showed `b1` persisted and router selected `b2` after reload | No |

## Fresh attack results

### 1) Capability mismatch scenarios

Passed.

What I tried:
- Backend declared `{FILE_WRITE, NETWORK}` but only observed `{FILE_WRITE}` with `required_capabilities={NETWORK}`
- Router selection where requested capability was not declared at all

Observed:
- `verify_observed_behavior()` raised `CapabilityMismatchError` with `declared but did not deliver`
- Router refused to select an incapable backend and raised `BackendUnavailableError`

Assessment:
- The original over-claim hole is closed for the meaningful case: a backend was selected/required for a capability and then failed to actually deliver it.

### 2) Router restart scenarios

Passed.

What I tried:
- Forced first backend failure with `max_attempts=1` so execution stopped after the first failed attempt
- Re-loaded router from persisted state and asked it to select again for the same `spec_id`

Observed on disk after first failed attempt:
- `failovers` contained the failed `b1` attempt
- `attempted` contained `['s-restart', 'b1']`

Observed after restart:
- Router selected `b2`, not `b1`

Assessment:
- The durability bug from v1 is fixed. Attempt history and failover history now survive restart at the right moments.

### 3) Concurrent-execution edge case (single-threaded scope)

Not a blocker for this phase, but worth noting.

What I tried:
- Created a backend with `max_concurrent_runs=1`
- Called `select_backend()` for two different `spec_id`s without executing either first

Observed:
- Router returned the same backend both times
- `max_concurrent_runs` is stored in `BackendCapabilities` (`capabilities.py:31`) but not enforced anywhere in router selection (`router.py:74-99`)

Assessment:
- This is a real limitation, but in current scope it is not a regression against the two Phase 6 blockers and does not break the tested single-run fallback/restart guarantees.
- If concurrent routing becomes in-scope soon, this should become an explicit follow-up item.

## Additional quality notes

Non-blocking:
- Semantic parity tests remain fairly shallow. They validate terminal status and artifact-count parity (`tests/accelerators/test_adapters.py:57-93`) but do not deeply compare summaries, timestamps, partial-result semantics, or richer evidence-chain behavior.
- Router docs mention availability/health, but current implementation models availability mainly through capability filtering, adapter presence, and runtime failure/failover.

These are valid hardening opportunities, but I would not hold Phase 6 on them given the stated scope and the fact that the previously blocking defects are now actually fixed and verified.

## Final signoff recommendation

Sign off Phase 6.

Reasoning:
- Both prior blockers are fixed in code
- Both fixes are covered by targeted tests
- Independent adversarial repros confirmed the intended behavior, including restart safety
- I found one concurrency-related design gap (`max_concurrent_runs` unenforced), but within the current single-threaded/tested scope it is not severe enough to fail the phase

Recommended follow-up after signoff:
- Add explicit concurrency-limit enforcement or document it as out of scope
- Deepen semantic-parity tests before expanding adapter diversity
