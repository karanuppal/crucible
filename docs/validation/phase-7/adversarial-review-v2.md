# Phase 7 Adversarial Review — Second Pass

## Verdict: FAIL

The four blockers from adversarial review v1 are fixed:
- Orchestrator happy path now produces real evidence, registers runs, and completes successfully
- `BootstrapState` now round-trips `create_github_repo`, `github_owner`, and `github_visibility`
- Phase 5 validation matrix no longer overclaims GitHub coverage
- Fan-in conflict attribution now credits all touching tasks via `overlap_map`

I also ran the full suite:
- `uv run pytest tests/ -v`
- Result: **363 passed**

However, fresh adversarial attacks found a new blocking issue in fan-in integration and one additional orchestrator robustness issue.

## Blocker table

| Area | Prior blocker | Status | Evidence | Notes |
|---|---|---|---|---|
| Orchestrator happy path | Synthesized empty evidence caused validator downgrade and blocked completion | FIXED | `tests/orchestrator/test_orchestrator.py::test_full_loop_completes_with_real_evidence` passes; direct repro returned `OrchestratorPhase.DONE`, completed `['t1', 't2']`, failed `[]` | `_build_criterion_results()` now materializes evidence files, records via `RunRegistry`, and stamps real `run_id`s |
| Greenfield state persistence | `BootstrapState` dropped GitHub config fields | FIXED | `tests/workflows/test_greenfield.py::test_github_fields_roundtrip` passes; source now persists/restores all three GitHub fields in `to_dict()` / `from_dict()` | Resume contract for GitHub config is now preserved |
| Phase 5 matrix accuracy | Matrix overclaimed GitHub remote validation | FIXED | `docs/validation/phase-5/validation-matrix.md` now says `⚠️ code-present, integration test pending` | Claim is now aligned with actual coverage |
| Fan-in conflict attribution | Conflict reports only credited current task | FIXED | `src/agentic_harness/integration/fan_in.py` uses `overlap_map`; direct conflict repro returned `shared.py ['t1', 't2']` | Attribution is now correct for overlapping branches |
| Fan-in invalid branch handling | Fresh attack: non-existent branch merged as success | NEW BLOCKER | Direct repro with `branch_name='missing/branch'` returned `status integrated`, `conflict_count 0`, `error ''` | `git merge missing/branch` exits non-zero, but code treats every non-zero merge as conflict, gathers zero conflict files, aborts, then still returns `INTEGRATED` if `conflicts` is empty. This is a false-success path and is signoff-blocking. |
| Orchestrator failure-mode state | Fresh attack: mid-loop crash leaves inconsistent failure accounting | NEW FINDING (non-blocking) | Repro with backend crash on second task returned `phase DONE`, completed `['t1']`, failed `['t2', 't2']` | Orchestrator survives and does not corrupt completion, but double-counts a failed task and still lands in `DONE` with partial success. Worth fixing for restart safety / audit cleanliness, but not as severe as the fan-in false-success bug. |
| Greenfield `create_github_repo=True` without `gh` | Fresh attack requested fail-closed check | PASS / fail-closed | Repro returned `BootstrapError: Step create_github_repo failed: gh CLI not authenticated: gh not found` | Behavior is acceptable: it fails closed rather than silently skipping remote creation |

## Details

### 1) Prior blocker: orchestrator happy path is fixed
I re-checked the exact failure mode from v1.

What changed:
- `_build_criterion_results()` now writes a real evidence file per criterion
- It creates `ArtifactRef`s, records them through `RunRegistry.record_run(...)`, and uses the registry-stamped `run_id`
- The orchestrator now calls the integration phase when an integrator is provided

Validation:
- `tests/orchestrator/test_orchestrator.py` covers the happy path
- Direct repro produced:
  - `happy_phase OrchestratorPhase.DONE`
  - `completed ['t1', 't2']`
  - `failed []`

Conclusion:
- The original blocker is genuinely fixed

### 2) Prior blocker: BootstrapState GitHub fields are fixed
I re-checked serialization.

What changed:
- `BootstrapState.to_dict()` now includes:
  - `create_github_repo`
  - `github_owner`
  - `github_visibility`
- `BootstrapState.from_dict()` restores them

Validation:
- `tests/workflows/test_greenfield.py::test_github_fields_roundtrip` passes

Conclusion:
- The resume-state regression from v1 is fixed

### 3) Prior blocker: Phase 5 matrix wording is fixed
I re-read `docs/validation/phase-5/validation-matrix.md`.

What changed:
- The GitHub row now explicitly says integration coverage is still pending

Conclusion:
- The documentation overclaim from v1 is fixed

### 4) Prior blocker: fan-in conflict attribution is fixed
I re-ran the exact style of overlap repro from v1.

What changed:
- `integrate()` now computes `overlap_map = self.detect_overlap(outputs)`
- On merge conflict, it attributes the conflicting file to all touching task IDs

Validation:
- Direct repro with `feature/a` and `feature/b` both editing `shared.py` returned:
  - `status conflict`
  - `conflict shared.py ['t1', 't2']`

Conclusion:
- The attribution bug from v1 is fixed

## Fresh attacks

### A) Orchestrator state under failure modes (mid-loop crash)
Attack:
- Custom backend completed task 1
- Then raised during task 2 execution

Observed result:
- `phase OrchestratorPhase.DONE`
- `completed ['t1']`
- `failed ['t2', 't2']`

Assessment:
- Good: the orchestrator does not collapse the whole build when one task crashes
- Bad: the same failed task can be appended twice (`execute` failure, then `validate` non-complete path), which pollutes state and ledger semantics
- This is a robustness issue, but not worse than partial-success semantics. I would fix it, but I would not block solely on this if the fan-in bug did not exist.

### B) Fan-in with non-existent branches
Attack:
- Passed `SubAgentOutput(... branch_name='missing/branch' ...)` into `FanInIntegrator.integrate()`

Observed result:
- `status integrated`
- `conflict_count 0`
- `error ''`

Why this happens:
- `git merge missing/branch` returns non-zero
- The code assumes any non-zero merge means merge conflict
- `_get_conflict_files()` returns an empty list for a missing branch
- `merge --abort` is attempted
- Since `conflicts` remains empty, the function falls through to `IntegrationStatus.INTEGRATED`

Assessment:
- This is a real correctness bug
- It creates a false-success integration result when an input branch does not exist
- This is signoff-blocking because it breaks the trust model of integration status

### C) Greenfield with `create_github_repo=True` but no `gh`
Attack:
- Simulated missing `gh` CLI while leaving normal `git` behavior intact

Observed result:
- `BootstrapError: Step create_github_repo failed: gh CLI not authenticated: gh not found`

Assessment:
- Correct fail-closed behavior
- No new issue found here

## Final recommendation

**Do not mark Phase 7 PASS yet.**

Recommended minimum fix before signoff:
- In `FanInIntegrator.integrate()`, distinguish:
  - real merge conflicts
  - invalid/missing branch refs
  - other git merge failures
- If `git merge` fails and `_get_conflict_files()` is empty, return `FAILED` with the git stderr instead of `INTEGRATED`
- Add a targeted regression test for a non-existent branch input

Recommended follow-up hardening (non-blocking but worthwhile):
- Deduplicate `failed_tasks` in the orchestrator or prevent the same task from being failed in both execute and validate phases
- Consider explicit persisted orchestrator checkpoints if restart safety is meant literally rather than best-effort

If the non-existent-branch fan-in bug is fixed and covered by test, I would recommend **PASS** on the next review.