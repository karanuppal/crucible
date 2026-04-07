# Phase 7 Adversarial Review

## Verdict: FAIL

Phase 7 materially improves the repo by adding the missing files called out in the final holistic review, but it does **not** fully close the integration gaps. The most important issue is that the new top-level orchestrator cannot actually drive a successful build through the advertised loop: on the nominal happy path it deterministically fails validation and ends `BLOCKED`. There is also a resume-state bug in greenfield GitHub bootstrap that drops the GitHub configuration across persistence, which breaks the remote-repo creation/resume contract. Finally, the new Phase 5 validation matrix overstates test coverage for GitHub remote creation.

## Findings (blocking)

### 1) Orchestrator happy path is not actually successful end-to-end

**What I found**
- `src/agentic_harness/orchestrator/orchestrator.py` claims to wire `spec -> ambiguity -> decompose -> schedule -> execute -> validate -> lessons -> integration`.
- In practice, `_build_criterion_results()` fabricates `CriterionResult` objects with:
  - `verdict=PASS if run_result.artifact_paths else BLOCKED`
  - `evidence_artifacts=[]`
- `src/agentic_harness/validation/criterion.py` requires a PASS to include at least one integrity-verifiable artifact (`has_real_evidence()` returns `False` when `evidence_artifacts` is empty).
- `src/agentic_harness/validation/validator.py` downgrades any vacuous PASS to FAIL.

**Concrete evidence**
- Running a minimal happy-path script against the new orchestrator produced:
  - `phase OrchestratorPhase.BLOCKED`
  - `completed []`
  - `failed ['t1']`
  - `blocked_reason All tasks failed: ['t1']`
- So even when the backend returns `AdapterStatus.COMPLETE`, the orchestrator does not complete a task successfully.

**Why this blocks signoff**
- The final review’s top missing piece was a real top-level orchestrator/build loop.
- A loop that is structurally present but cannot complete its own happy path does not close that gap.

### 2) Greenfield GitHub remote creation is not resume-safe because persisted state drops GitHub config

**What I found**
- `src/agentic_harness/workflows/greenfield.py` adds optional GitHub steps:
  - `STEP_CREATE_GITHUB_REPO`
  - `STEP_PUSH_TO_GITHUB`
- Resume verification exists in `_verify_step_artifacts()`.
- But `BootstrapState.to_dict()` and `BootstrapState.from_dict()` do **not** persist/restore:
  - `create_github_repo`
  - `github_owner`
  - `github_visibility`

**Concrete evidence**
- Serializing and reloading a state built from:
  - `create_github_repo=True`
  - `github_owner='me'`
  - `github_visibility='public'`
- produces restored config values:
  - `create_github_repo=False`
  - `github_owner=''`
  - `github_visibility='private'`

**Why this blocks signoff**
- Phase 7 explicitly set out to close the “GitHub remote repo creation in greenfield bootstrap” gap.
- Persisted resume is part of the bootstrap contract.
- Today, a persisted resume can silently forget that GitHub creation was requested, so the remote-side portion is not reliably integrated.

### 3) Phase 5 validation matrix claims GitHub remote coverage that the tests do not actually provide

**What I found**
- `docs/validation/phase-5/validation-matrix.md` includes:
  - `GitHub remote creation (optional) | (gh CLI integration) | create_github_repo + push_to_github steps | ✅`
- There are no tests covering GitHub repo creation/push behavior.

**Concrete evidence**
- Repository search across `tests/` found no tests for:
  - `create_github_repo=True`
  - `STEP_CREATE_GITHUB_REPO`
  - `_create_github_repo`
  - `_push_to_github`
  - `gh repo create`
  - existing-repo idempotency for GitHub creation
- `tests/workflows/test_greenfield.py` explicitly tests only the default path where `create_github_repo=False`.

**Why this blocks signoff**
- One of the four Phase 7 deliverables was validation matrices for phases 4/5/6.
- A matrix that marks uncovered functionality as validated is not an accurate signoff packet.

## Findings (non-blocking)

### 1) Orchestrator wiring is still partial, not full-system glue
- The orchestrator constructs `RunGraph`, `SpawnController`, and `CircuitBreaker`, but execution bypasses `SpawnController` and `RunGraph` entirely and calls `Router.execute_with_fallback()` directly.
- “Decomposition” is still externalized: `run_build()` requires the caller to hand it `tasks` up front rather than deriving them from the spec.
- “Integration” is only a phase label; `run_build()` sets `current_phase = INTEGRATE` and then immediately moves on to lesson capture. It does not invoke `FanInIntegrator` or any post-integration validation.

### 2) Ledger coverage is incomplete relative to the claimed lifecycle
- Events are emitted for:
  - `spec.created`
  - `task.created`
  - `run.spawned`
  - `validation.completed`
  - `failure.classified`
  - `build.completed`
- There are no ledger events for:
  - ambiguity gate decision
  - scheduling decisions/dispatch
  - integration start/result
  - lesson capture
  - ambiguity block terminal event
- So “ledger events at each major transition” is not fully satisfied.

### 3) Ambiguity gate blocks correctly, but block-state observability is thin
- `run_build()` does correctly halt on unsafe ambiguity outcomes and returns `current_phase = BLOCKED` with a reason.
- But it does not emit a corresponding ledger event for the ambiguity block, which weakens auditability.

### 4) Failure classification is too coarse
- `_failed_task()` always classifies failures as `FailureClass.VALIDATION_FAILURE`, even for router/dispatch/runtime exceptions.
- It does feed the circuit breaker, but the routing is not semantically precise.

### 5) Fan-in integration does not perform overlap detection pre-flight inside `integrate()`
- `detect_overlap()` exists and works.
- `integrate()` does not call it before merging; it only discovers overlap indirectly when git merge conflicts happen.
- That means the “pre-flight overlap detection” requirement is only partially satisfied at API level, not by the integration workflow itself.

### 6) Conflict reports under-identify the participants
- On a merge conflict, `IntegrationConflict.conflicting_task_ids` is populated with only the task currently being merged.
- In a repro where `feature/a` and `feature/b` both modify `shared.py`, the conflict report returned `shared.py ['t2']` rather than both task IDs.
- Conflict detection exists, but conflict attribution is incomplete.

### 7) Fan-in result statuses are narrower than the docstring suggests
- The module docstring mentions validation after merge, but `integrate()` returns `INTEGRATED` immediately after clean merges.
- `IntegrationStatus.VALIDATED` is defined but not used by the workflow.

### 8) Phase 4 and Phase 6 matrices look materially better aligned than Phase 5
- I did not find equivalent obvious over-claiming in the new Phase 4 or Phase 6 matrices.
- The most significant matrix accuracy problem is Phase 5’s GitHub row.

## Coverage of original 4 gaps from final review

### 1) Top-level orchestrator (`orchestrator/orchestrator.py`)
**Status: PARTIALLY CLOSED, NOT SUFFICIENT**
- The file now exists and stitches together many lower-level modules.
- It correctly blocks on ambiguity and does attempt execute/validate/lesson phases.
- But it does not complete the happy path, does not actually invoke fan-in integration, does not derive tasks from spec, and does not fully ledger major transitions.

### 2) Fan-in integration workflow (`integration/fan_in.py`)
**Status: MOSTLY CLOSED WITH OBSERVATIONS**
- The file now exists.
- Clean merges work.
- Merge conflicts are detected.
- `detect_overlap()` does identify overlapping files.
- `to_report()` produces a serializable report.
- Remaining gaps: pre-flight overlap detection is not integrated into `integrate()`, conflict attribution is incomplete, and no post-merge validation is performed.

### 3) GitHub remote repo creation in greenfield bootstrap
**Status: PARTIALLY CLOSED, NOT SIGNOFF-READY**
- Optional GitHub repo creation and push steps now exist.
- Existing-repo idempotency is attempted via the “already exists” check.
- Resume verification logic exists.
- But persisted state drops the GitHub config, so resumed bootstraps can silently skip the remote portion. Test coverage for this feature is also missing.

### 4) Validation matrices for Phases 4/5/6
**Status: PARTIALLY CLOSED**
- The previously-missing matrices now exist for all three phases.
- Phase 4 and Phase 6 appear broadly aligned with existing tests.
- Phase 5 is not fully accurate because it marks GitHub remote creation as validated without corresponding tests.

## Signoff recommendation

**Do not sign off Phase 7 as PASS yet.**

Recommended minimum fixes before signoff:
- Make the orchestrator able to complete a genuine happy path:
  - produce real `ArtifactRef` evidence,
  - record runs in `RunRegistry`,
  - pass validated evidence through the validator instead of fabricating vacuous PASS results.
- Persist and restore GitHub bootstrap config fields in `BootstrapState.to_dict()` / `from_dict()`.
- Add tests for:
  - `create_github_repo=False` skip behavior,
  - `create_github_repo=True` creation path,
  - resume verification of GitHub steps,
  - existing-repo idempotency,
  - push/remote behavior.
- Fix `docs/validation/phase-5/validation-matrix.md` so it matches actual coverage.
- Consider invoking `detect_overlap()` inside `FanInIntegrator.integrate()` and include both sides in `conflicting_task_ids`.

If those issues are fixed, I would expect a re-review to land at **PASS WITH OBSERVATIONS** or **PASS**, depending on whether orchestration/integration coverage is tightened further.