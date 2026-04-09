# Crucible v6.1 Execution Plan

**Version:** 1.0  
**Date:** 2026-04-08  
**Status:** Execution-ready

## Goal

Implement `docs/crucible-spec-v6.1.md` so the runtime uses a thin four-class control plane while preserving rich failure evidence, durable loop control, strong tests, and the v5.4/v6 design intent where compatible.

## Required v6.1 outcomes

- Runtime uses exactly 4 top-level control-plane classes:
  - `retryable`
  - `needs_user_input`
  - `stuck_or_repeating`
  - `terminal_nonrecoverable`
- Recovery specificity moves out of top-level taxonomy and into evidence/hints/metadata.
- Attempt types remain:
  - `build`, `repair`, `debug`, `review`, `salvage`, `integrate`, `revalidate`
- Attempt types are treated as role/phase semantics, not LLM-vs-non-LLM lanes.
- Budgets are raised/rebalanced to v6.1 defaults, including `deep_recovery_budget`.
- Selector/runtime/tests/docs all reflect the new model.

## Phase 0 — Read + baseline audit

### Work
- Read before modifying code:
  - `docs/crucible-spec-v6.1.md`
  - `docs/crucible-spec-v6.md`
  - `docs/crucible-spec-v5.4.md`
  - `docs/execution-plan-v6.md`
- Inspect current runtime and tests:
  - failure evidence / taxonomy / selector
  - budget policy + tracker
  - attempt type semantics
  - runtime classification + selector integration
  - handoff / workflow / environment integration tests
- Capture current `git status` and use `git diff` between phases.

### Reviewer gate
- Confirm implementation checklist covers every v6.1 deliverable.
- Confirm no code edits begin before spec/code review is complete.

### Exit criteria
- Complete implementation map exists.
- High-risk compatibility points identified.

## Phase 1 — Four-class control plane

### Work
- Collapse top-level failure/control classification to the four v6.1 classes.
- Update shared failure enums/dataclasses used by policy/runtime.
- Preserve detail through evidence fields, hints, metadata, signatures, and prior-attempt context.
- Update taxonomy helpers to use the four-class model.

### Expected files
- `src/crucible/failures/evidence_packet.py`
- `src/crucible/failures/taxonomy.py`
- `src/crucible/runtime/run_executor.py`
- `tests/failures/test_evidence_packet.py`
- `tests/failures/test_failure_taxonomy.py`
- `tests/runtime/test_failure_classification_v54.py`

### Test gate
- Targeted failure/evidence/taxonomy/runtime-classification tests pass.

### Reviewer gate
- Verify exactly four top-level classes exist in runtime control code.
- Verify removed specificity reappears only as hints/evidence, not hidden replacement classes.

### Exit criteria
- No legacy eight-class control-plane taxonomy remains in active runtime policy code.

## Phase 2 — Selector + runtime behavior

### Work
- Update next-action selection so class drives control policy only:
  - `retryable` → autonomous continuation
  - `needs_user_input` → pause with blocker packet
  - `stuck_or_repeating` → materially different strategy / deep recovery
  - `terminal_nonrecoverable` → evidence-backed stop
- Keep attempt-type selection contextual via hints/metadata/history.
- Ensure runtime classification feeds selector correctly.
- Preserve durable evidence and status emissions.

### Expected files
- `src/crucible/failures/next_action_selector.py`
- `src/crucible/runtime/run_executor.py`
- `src/crucible/runner/handoff_controller.py`
- `tests/failures/test_next_action_selector.py`
- `tests/runner/test_handoff_controller.py`
- `tests/runtime/test_closed_loop_runtime_e2e.py`

### Test gate
- Targeted selector/runtime/handoff tests pass.
- Selector/runtime integration proves the 4-class model drives real task flow.

### Reviewer gate
- Verify class is used for control, not over-diagnosis.
- Verify repeated-failure handling forces materially different recovery behavior.

### Exit criteria
- Runtime control flow matches v6.1 semantics.

## Phase 3 — Budgets + attempt semantics

### Work
- Raise/rebalance budgets to v6.1 defaults:
  - `build_attempt_budget = 3`
  - `repair_attempt_budget = 8`
  - `debug_attempt_budget = 4`
  - `review_rejection_budget = 3`
  - `salvage_attempt_budget = 4`
  - `integration_attempt_budget = 3`
  - `deep_recovery_budget = 6`
- Update tracker + selector budget handling.
- Clarify in code/tests that attempt types are role semantics and may all use LLM workers.

### Expected files
- `src/crucible/policy/budgets.py`
- `src/crucible/policy/budget_tracker.py`
- `src/crucible/state/attempt_type.py`
- `tests/policy/test_budget_tracker.py`
- `tests/state/test_attempt_type.py`
- `tests/failures/test_next_action_selector.py`

### Test gate
- Targeted policy/state/selector tests pass.

### Reviewer gate
- Verify budget names/defaults match v6.1.
- Verify deep recovery behavior is covered and not conflated with ordinary retries without explicit tests.

### Exit criteria
- Budget behavior is spec-aligned and tested.

## Phase 4 — Docs + full suite hardening

### Work
- Update architecture/docs where runtime model changed.
- Add/adjust substantial tests for:
  - four-class model
  - hint/evidence behavior
  - budget behavior
  - attempt-type semantics
  - selector/runtime integration
- Run full relevant test suite.

### Expected files
- `docs/architecture.md`
- possibly `docs/crucible-spec-v6-review-notes.md` if helpful
- all touched tests

### Test gate
- Full relevant suite passes cleanly.

### Reviewer gate
- Independent reviewer pass against `docs/crucible-spec-v6.1.md`.
- If findings exist: fix, rerun affected tests, rerun full suite, repeat reviewer pass until clean.

### Exit criteria
- Docs and code agree.
- Full suite green.
- Reviewer clean pass recorded.

## Test plan

### Targeted suites by phase
- `tests/failures/test_evidence_packet.py`
- `tests/failures/test_failure_taxonomy.py`
- `tests/failures/test_next_action_selector.py`
- `tests/policy/test_budget_tracker.py`
- `tests/state/test_attempt_type.py`
- `tests/runner/test_handoff_controller.py`
- `tests/runtime/test_failure_classification_v54.py`
- `tests/runtime/test_closed_loop_runtime_e2e.py`
- `tests/environment/test_existing_repo.py`
- `tests/workflows/test_intake.py`

### Full relevant suite before finalizing
- `pytest tests/failures tests/policy tests/state tests/runner tests/runtime tests/environment tests/workflows`

## Final acceptance checklist

- [ ] Exactly four top-level control-plane classes exist.
- [ ] Specificity lives in evidence/hints/metadata, not extra top-level classes.
- [ ] Attempt types remain core semantic roles and are documented/tested that way.
- [ ] Budgets match v6.1 defaults, including deep recovery.
- [ ] Selector/runtime integration covers retryable vs user-input vs stuck vs terminal behavior.
- [ ] Full relevant suite passes.
- [ ] Reviewer pass is clean after any fixes.
