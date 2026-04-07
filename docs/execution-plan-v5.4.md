# Crucible v5.4 Execution Plan

**Version:** 1.0  
**Date:** 2026-04-07  
**Status:** Ready for review

---

## Overview

v5.4 transforms Crucible from a durable verifier into a **deterministic closed-loop software execution harness**. The core shift: Crucible owns the repair loop, not the outer LLM.

This plan breaks v5.4 into 6 sequential phases. Each phase is gated by tests + reviewer agent before proceeding.

---

## Phase 1: Attempt State Machine & Data Models

**Goal:** Define the new first-class data structures for attempts, workspaces, and failure evidence.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/state/attempt.py` | New `AttemptState` enum: `pending`, `running`, `completed_unverified`, `validated_pass`, `validated_fail`, `partial`, `blocked`, `abandoned`, `superseded` |
| `src/crucible/state/attempt_type.py` | New `AttemptType` enum: `build`, `repair`, `debug`, `review`, `salvage`, `integrate`, `revalidate` |
| `src/crucible/state/workspace_record.py` | `WorkspaceRecord` distinguishing `fresh`, `repair_basis`, `salvage_inherit`, `salvage_replay`, `partial_consume` |
| `src/crucible/failures/evidence_packet.py` | `FailureEvidencePacket` with: `failure_class`, `attempt_id`, `criterion`, `evidence_refs`, `timestamp`, `reproducible` |
| `src/crucible/failures/next_action_selector.py` | Deterministic function: `failure_class + attempt_history + evidence → NextAction` |
| `tests/state/test_attempt_state.py` | State enum completeness + transition validation tests |
| `tests/failures/test_next_action_selector.py` | Matrix test: each failure class → deterministic next action |

### Exit Criteria

- [ ] All attempt states and types defined as enums
- [ ] `WorkspaceRecord` distinguishes all lineage types
- [ ] `FailureEvidencePacket` schema complete
- [ ] `NextActionSelector` implements the full failure-class-to-action matrix from spec
- [ ] 20+ unit tests covering state transitions and action selection
- [ ] Reviewer agent passes

---

## Phase 2: Budget Policy Engine

**Goal:** Replace vague "retry count" with typed, bounded budgets per attempt type.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/policy/budgets.py` | `BudgetPolicy` dataclass with: `spawn_retry_budget`, `build_attempt_budget`, `repair_attempt_budget`, `debug_attempt_budget`, `review_rejection_budget`, `salvage_attempt_budget`, `integration_budget` |
| `src/crucible/policy/budget_tracker.py` | `BudgetTracker` that tracks spent vs remaining per attempt type, enforces limits, records exhaustion events |
| `src/crucible/policy/circuit_breaker.py` | `CircuitBreaker` policy: trips on loop detection, repeated symptom recurrence, or budget exhaustion |
| `tests/policy/test_budget_tracker.py` | Budget decrement, exhaustion detection, reset on new attempt type |
| `tests/policy/test_circuit_breaker.py` | Trip conditions, recovery policy, state persistence |

### Exit Criteria

- [ ] BudgetPolicy with all 7 budget types from spec
- [ ] BudgetTracker enforces limits and tracks exhaustion
- [ ] CircuitBreaker implements trip conditions from spec
- [ ] 15+ tests covering budget and circuit-breaker behavior
- [ ] Reviewer agent passes

---

## Phase 3: Role Handoff Controller

**Goal:** Explicit, deterministic transitions between Builder ↔ Reviewer ↔ Debugger ↔ Salvage ↔ Integrator.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/runner/handoff_controller.py` | `HandoffController` implementing spec Section 8: builder→reviewer→debugger→salvage→integrator rules |
| `src/crucible/runner/role_executor.py` | `RoleExecutor` spawns appropriate worker (builder/debugger/reviewer/salvage/integrator) based on attempt type |
| `src/crucible/runner/non_identical_rule.py` | `NonIdenticalRetryRule` enforces: new repair must differ from rejected attempt in prompt/role/backend/workspace/evidence/decomposition |
| `tests/runner/test_handoff_controller.py` | Test each handoff path from spec Section 8 |
| `tests/runner/test_non_identical_rule.py` | Verify identical retry is blocked after rejection |

### Exit Criteria

- [ ] HandoffController implements all 5 role handoff rules from spec
- [ ] RoleExecutor spawns correct worker type for each attempt type
- [ ] NonIdenticalRetryRule blocks blind respawn
- [ ] 20+ tests covering handoff paths
- [ ] Reviewer agent passes

---

## Phase 4: Closed-Loop Runtime Orchestrator

**Goal:** Replace the v5.3 single-pass executor with a deterministic loop that owns task closure.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/orchestrator/closed_loop_executor.py` | New `ClosedLoopExecutor` implementing spec Section 6: task lifecycle loop until terminal state |
| `src/crucible/orchestrator/task_state_machine.py` | `TaskStateMachine` implementing spec Section 7.3 state transitions |
| `src/crucible/orchestrator/run_closure.py` | `RunClosure` enforcing: all tasks complete → integration → post-validation → terminal |
| `src/crucible/runtime/run_executor.py` | **Modified** to call ClosedLoopExecutor instead of single-pass logic |
| `tests/orchestrator/test_closed_loop_executor.py` | End-to-end test: task enters `queued` → cycles through attempts → reaches `complete` or `blocked` |
| `tests/orchestrator/test_task_state_machine.py` | All state transitions from spec Section 7.3 |
| `tests/orchestrator/test_run_closure.py` | Verify run closure invariants |

### Exit Criteria

- [ ] ClosedLoopExecutor owns the full task lifecycle loop
- [ ] TaskStateMachine implements all transitions from spec
- [ ] RunClosure enforces terminal invariants
- [ ] 30+ integration tests covering loop behavior
- [ ] Reviewer agent passes

---

## Phase 5: Workspace Lineage & Evidence Persistence

**Goal:** Every attempt knows its workspace origin; evidence is durably stored.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/workspace/lineage.py` | `WorkspaceLineageTracker` tracks: fresh start, repair basis, salvage inherit, partial consume |
| `src/crucible/workspace/manager.py` | `WorkspaceManager` creates/cleans/manages per-attempt workspaces with lineage tagging |
| `src/crucible/evidence/store.py` | `EvidenceStore` persists `FailureEvidencePacket`, validation outputs, reviewer verdicts |
| `src/crucible/evidence/manifest.py` | `EvidenceManifest` per attempt: all artifacts, diffs, logs, criterion results |
| `tests/workspace/test_lineage.py` | Verify lineage is tracked for fresh/repair/salvage paths |
| `tests/evidence/test_store.py` | Verify evidence packet persistence and retrieval |

### Exit Criteria

- [ ] WorkspaceLineageTracker distinguishes all 5 lineage types
- [ ] WorkspaceManager creates/isolates per-attempt workspaces
- [ ] EvidenceStore persists packets durably
- [ ] EvidenceManifest captures all required artifacts per attempt
- [ ] 15+ tests
- [ ] Reviewer agent passes

---

## Phase 6: Chat Surface & OpenClaw Integration

**Goal:** Update runtime status reporting to expose rich semantic states.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/runtime/openclaw_tool.py` | **Modified** to expose: `building`, `repairing`, `debugging`, `awaiting_review`, `awaiting_user`, `salvaging`, `integrating`, `blocked`, `complete` |
| `src/crucible/runtime/status_emitter.py` | `StatusEmitter` emits lifecycle events to chat surface |
| `src/crucible/runtime/resume_handler.py` | Handles `crucible run --resume` with full state reconstruction |
| `tests/runtime/test_status_emitter.py` | Verify event emission matches state transitions |
| `tests/runtime/test_resume_handler.py` | Verify full state reconstruction after interrupt |

### Exit Criteria

- [ ] OpenClaw tool reports all 9 runtime semantic states
- [ ] StatusEmitter emits events on state transitions
- [ ] Resume handler reconstructs complete runtime state
- [ ] 10+ tests
- [ ] Reviewer agent passes

---

## Phase Dependencies

```
Phase 1 ──┬──> Phase 2 ──> Phase 3 ──> Phase 4 ──> Phase 5 ──> Phase 6
          │         │          │          │          │
          └─────────┴──────────┴──────────┴──────────┘
                     (Phase 2-3 can parallel after Phase 1)
```

**Constraint:** Phases 2-3 can run in parallel after Phase 1 completes. Phases 4-5-6 are sequential and depend on prior phases.

---

## Test Gating Strategy

Each phase requires:
1. **Unit tests** for new components (minimum coverage below)
2. **Integration tests** for cross-component behavior
3. **Reviewer agent** sign-off before phase merge

| Phase | Min Tests | Key Coverage |
|-------|-----------|--------------|
| 1 | 20 | State enums, action selection matrix |
| 2 | 15 | Budget tracking, circuit breaker |
| 3 | 20 | All handoff paths, non-identical rule |
| 4 | 30 | Full loop, all state transitions |
| 5 | 15 | Lineage tracking, evidence persistence |
| 6 | 10 | Status emission, resume |

**Total minimum:** 110 tests

---

## Reviewer Agent Protocol

1. Spawn reviewer sub-agent with:
   - Phase spec section
   - Implementation files
   - Test files + coverage report
2. Reviewer checks:
   - All spec requirements implemented
   - Test coverage adequate
   - No regressions on existing 542 tests
3. Reviewer outputs: `APPROVED` or `REJECTED` with specific feedback
4. If rejected: fix + re-review before proceeding

---

## Open Questions

- Should budgets be configurable per-task or global?
- How to handle partial integration when some tasks fail?
- Resume should reconstruct attempt history — verify persistence layer supports this

---

## Next Step

Once approved, begin **Phase 1: Attempt State Machine & Data Models**.