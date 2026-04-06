# Phase 2 Adversarial Review

- Verdict: FAIL

## Findings (blocking) with concrete evidence/repro

### 1) Orphans are possible; child ownership is not enforced
- Spec requires:
  - Every child has exactly one parent run or one owning task (§9.2)
  - No orphaned runs after forced parent termination (Execution Plan Phase 2 blocking gate)
  - Non-blocking children may continue only if explicitly reattached to another owning task or integration run (§9.2)
- Implementation gap:
  - `RunGraph.spawn()` accepts any `parent_run_id` string and still creates the child even if that parent does not exist. It only registers parent/child linkage if `parent_run_id in self._nodes` (`src/agentic_harness/runner/run_graph.py:68-95`), but the node is still created with `parent_run_id` set (`run_graph.py:78-83`).
  - There is no validation that a spawned child has a real owner.
  - There is no reattach API at all; only `detach_child()` exists (`run_graph.py:132-137`).
- Concrete repro:
  - `g = RunGraph()`
  - `child = g.spawn("t1", RunRole.BUILDER, parent_run_id="missing-parent")`
  - Result: child exists, `child.parent_run_id == "missing-parent"`, but no parent tracks it. That is an orphan by construction.
- Additional orphan path:
  - If a parent is marked terminal via `update_status(parent, RunStatus.KILLED)`, nothing cascades, nothing validates detached children, and nothing reassigns them (`run_graph.py:100-102`).
  - `test_detached_survives_cancellation` explicitly encodes this behavior and treats a detached child remaining `PENDING` after parent kill as success (`tests/runner/test_run_graph.py:69-79`). But spec says survival is allowed only if explicitly detached **and reassigned**; reassignment is missing.
- Impact:
  - Active runs can outlive parents without an owning task/integration run.
  - Execution Plan Phase 2 orphan-prevention gate is not met.

### 2) Cancellation propagation is incomplete and can be bypassed
- Spec requires:
  - Cancelling a parent should cancel all blocking children by default (§9.3)
  - Review and integration runs attached to a cancelled task should also cancel unless still needed (§9.3)
- Implementation gap:
  - Parent cancellation is not wired into `RunGraph.update_status()`; changing parent status to `KILLED` has no effect on children (`run_graph.py:100-102`).
  - `SpawnController.cancel_blocking_children()` exists, but it is a separate opt-in helper and is never invoked automatically when parent status changes (`src/agentic_harness/runner/spawn_controller.py:165-177`).
  - It only cancels children in `RUNNING` state; `PENDING` blocking children survive (`spawn_controller.py:170-175`). That leaks cancellation to children that have not started yet.
  - There is no task-level cancellation semantics for reviewer/integrator runs, and no notion of “still needed by another surviving task.”
- Concrete repro:
  - Spawn parent + blocking child.
  - Call `graph.update_status(parent, RunStatus.KILLED)`.
  - Child remains `PENDING` or `RUNNING`; nothing auto-cancels.
  - Even if caller remembers to invoke `cancel_blocking_children(parent)`, a `PENDING` child is skipped and survives.
- Impact:
  - Cancellation correctness depends on external caller discipline.
  - Blocking children can leak past cancelled parents.

### 3) Circuit breaker can be trivially evaded by superficial variation
- Spec requires:
  - Loop detection should work on semantically repeated failure, not string match only (Execution Plan Phase 2)
  - Slightly varied wording should still count as the same failure when root cause is the same (Execution Plan Phase 2 circuit breaker negative test)
  - Rejection ledger should prevent repeated retries of known-bad approaches without new evidence (§13.5)
- Implementation gap:
  - `should_trip()` only trips if all recent error signatures are exactly identical (`src/agentic_harness/runner/circuit_breaker.py:62-81`).
  - `get_error_signature()` is just exception type + first line prefix, or raw string truncation (`circuit_breaker.py:137-142`). No normalization, no semantic grouping.
  - `can_retry()` compares exact `approach` strings (`circuit_breaker.py:108-127`). Whitespace/casing/synonym changes bypass the ledger.
- Concrete repro:
  - Errors:
    - `ValueError("Module foo missing")`
    - `ValueError("module foo missing")`
    - `ValueError("Module  foo missing ")`
  - These are semantically the same root cause, but produce different signatures and `len(set(task_errors)) != 1`, so breaker does not trip.
  - Rejection ledger bypass:
    - `record_approach("t1", "Edit setup.py", ...)`
    - `can_retry("t1", "edit setup.py")` returns `True`
    - `can_retry("t1", "Edit  setup.py")` returns `True`
- Impact:
  - Real loops are easy to keep alive by trivial rewording.
  - Core anti-loop requirement is not satisfied.

### 4) Timeout tracking can be bypassed or become incorrect
- Spec requires:
  - Timeout salvage and active-run visibility with last progress timestamp (§9.10, §9.11)
  - Controller restart should rehydrate mixed states correctly (Execution Plan Phase 2)
- Implementation gap:
  - `SpawnController.spawn()` applies `config.timeout_seconds`, but `check_timeouts()` ignores it and re-reads timeout from the role template (`src/agentic_harness/runner/spawn_controller.py:109-112` vs `150-153`). Per-run overrides are silently dropped.
  - `_active_runs` stores only `start_time`, not configured timeout, not backend handle, not last progress (`spawn_controller.py:102, 124`).
  - `RunGraphNode.last_progress_at` exists but is never updated anywhere (`run_graph.py:49-51, 100-102`).
  - Timeout is measured from spawn start only, not from progress/heartbeat, so long-running but healthy runs cannot extend liveness.
  - If controller process restarts, `_active_runs` is lost entirely and there is no persistence/rehydration path.
- Concrete repro:
  - Spawn with `SpawnConfig(timeout_seconds=5)` for a builder.
  - Wait >5s but <600s.
  - `check_timeouts()` still uses builder template timeout of 600, so the run does not time out.
- Impact:
  - Custom timeout policy is unenforced.
  - Timeout accounting is not durable and can lose track of live runs on restart.

### 5) No persistence/recovery layer exists for run graph, breaker, or active runs
- Spec requires:
  - Durable harness-owned state (§11, §17)
  - Restart/recovery tests for run graph, controller mixed states, breaker state, and active-run visibility (Execution Plan Phase 2)
- Implementation gap:
  - `RunGraph` is in-memory only (`src/agentic_harness/runner/run_graph.py:65-66`).
  - `CircuitBreaker` is in-memory only (`src/agentic_harness/runner/circuit_breaker.py:47-49`).
  - `SpawnController._active_runs` is in-memory only (`src/agentic_harness/runner/spawn_controller.py:102`).
  - No serializer, no file/DB backing, no rehydrate API, no ledger integration.
- Test evidence:
  - There are zero restart/recovery tests in Phase 2 test files.
  - The execution plan explicitly requires restart/recovery coverage for run graph, controller, circuit breaker, and active-run visibility; none is present.
- Impact:
  - After restart, the system loses active-run tracking, breaker history, and parent/child execution state.
  - This is a direct miss against both spec and validation matrix.

### 6) PARTIAL is only an enum value, not a real terminal state with salvage semantics
- Spec requires:
  - `partial` means usable artifacts were produced; outputs must be recorded in ledger and available for salvage/integration (§9.4)
- Implementation gap:
  - `PARTIAL` is merely treated as terminal in `_is_terminal()` (`run_graph.py:115-122`).
  - No method attaches artifacts upon partial completion.
  - No ledger exists here to record partial outputs.
  - No salvage/resume logic exists in `SpawnController`; `check_timeouts()` only marks `TIMED_OUT` (`spawn_controller.py:139-158`).
- Test evidence:
  - The only PARTIAL test is `assert g.is_blocking_child_complete(run_id)` after marking a node PARTIAL (`tests/runner/test_run_graph.py:44-49`).
  - That proves only “counts as terminal for one helper,” not “proper terminal state everywhere.”
- Impact:
  - PARTIAL is not implemented as specified; it is just another terminal enum.

## Findings (non-blocking)

### 7) Spawn result/run graph identity mismatch is papered over by tests
- `SpawnController.spawn()` creates a graph run ID internally, but returns the raw `SpawnResult` from `_spawn_fn`, whose `run_id` may differ (`src/agentic_harness/runner/spawn_controller.py:114-133`).
- Tests explicitly acknowledge this mismatch instead of enforcing identity (`tests/runner/test_spawn_controller.py:36-38, 78-80`).
- This will make downstream `poll/collect/kill` bookkeeping error-prone once backend handles are real.

### 8) Role templates are present for all 6 roles, but not obviously “sensible defaults” yet
- Completeness:
  - All six spec roles exist via enum + templates (`run_graph.py:29-35`, `spawn_controller.py:18-61`).
- Gaps:
  - No role-specific behavior beyond timeout/model/retry/evidence flag.
  - Comment/docstring references spec §9.3 for role templates, but role templates are not actually specified there; spec lists roles in §9.6.
  - Every role uses backend `codex`; no rationale, no backend capability fit, no isolation settings for reviewer separation.
- I would not block on the exact numbers, but the implementation is still shallow relative to spec intent.

### 9) Active-run visibility is underspecified and underimplemented
- Spec requires active run view with role, task association, last progress timestamp, current status, blocked reason (§9.11).
- Current implementation only exposes `RunGraph.get_active_runs()` returning nodes with default-zero timestamps and no blocked reason (`run_graph.py:139-141`).
- No dedicated active-run view object, no blocked-reason tracking, no stale-snapshot handling.

### 10) Test suite is much weaker than the Phase 2 validation matrix
- Missing tests for:
  - forced parent termination orphan scenarios
  - repeated `kill`
  - repeated `collect`
  - poll during terminal transition
  - race between completion and cancellation
  - restart/rehydration of any component
  - salvage success/failure paths
  - semantic-duplicate failures for breaker
  - stale active-run snapshots / ghost runs
- Also, tests import `pytest` but environment here lacked it, which prevented execution. That is an environment issue, not a code bug, but the signoff packet should include runnable commands/logs.

## Missing validation matrix items
- Run graph restart/recovery test: absent
- Controller restart with mixed states: absent
- Idempotency logs for `kill` and `collect`: no `collect` implementation exists; no idempotency tests
- Race test between completion and cancellation: absent
- Salvage transcript showing exact checkpoint resume: absent; no salvage logic exists
- Salvage blocked on insufficient artifacts: absent
- Breaker persistence across restart: absent
- Negative test for semantically same failures with varied wording: absent
- Active-run visibility rebuild after restart without ghosts/missing runs: absent
- Before/after visibility snapshots and transition timeline: absent

## Spec gaps
- The spec is clear that detached/non-blocking children must be explicitly reattached, but it does not define the exact state transition API or whether reattachment is to task, run, or integration object first. The implementation still misses the requirement, but the concrete API shape could be specified more tightly.
- The spec calls for a rejection ledger with “what lesson should constrain the next attempt” (§13.5). The current code records no structured lesson field, but the spec could be more explicit about schema and normalization rules.
- Active-run visibility requires `blocked reason`, but the RunState required fields in §11.1 do not explicitly include `blockedReason`. That field should probably be added to the state contract.
- The spec implies persistence strongly via §§11 and 17, but Phase 2 might benefit from an explicit “minimum persistence scope” statement: run graph nodes, active-run tracker, rejection ledger, and breaker counters must survive restart.

## Recommendations
- Enforce ownership invariants at spawn time:
  - reject unknown `parent_run_id`
  - support explicit owner types for orchestrator-owned runs
  - add `reattach_child()` with validated new owner
- Make cancellation deterministic:
  - a parent terminal transition should trigger child-cancellation policy automatically
  - cancel blocking children in both `PENDING` and `RUNNING`
  - encode task-level reviewer/integrator cancellation rules
- Replace exact-string anti-loop logic with normalized/semantic grouping:
  - normalize casing/whitespace
  - store structured failure class + root-cause key
  - compare approaches using normalized canonical form and evidence delta
- Fix timeout accounting:
  - persist per-run timeout on the node/state
  - track `last_progress_at` and optionally heartbeat-based liveness
  - do not recompute timeout solely from role template
- Add persistence now, not later:
  - serialize run graph nodes, active-run metadata, breaker counters, rejection ledger
  - implement rehydrate APIs and restart tests
- Make PARTIAL first-class:
  - require artifact refs and summary before PARTIAL terminalization
  - expose salvage planning/resume from partial state
- Align controller identity model:
  - keep graph `run_id` and backend handle linked explicitly
  - make `spawn/poll/collect/kill` operate on one consistent run record
- Upgrade tests to match the validation matrix before claiming Phase 2 completion.
