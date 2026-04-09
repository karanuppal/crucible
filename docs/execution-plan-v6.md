# Crucible v6 Execution Plan

**Version:** 1.0
**Date:** 2026-04-08
**Status:** Ready for review

---

## Overview

v6 adds LLM-augmented autonomous recovery to Crucible. The core shift: **the harness never gives up without trying the LLM first**.

v5.4 correctly maps failures to actions, but often chooses `AWAITING_USER` or no-op actions. v6 replaces these with LLM-driven recovery attempts.

---

## Phase 1: Recovery Infrastructure

**Goal:** Build the recovery subsystem that invokes the LLM for problem-solving.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/recovery/__init__.py` | Module exports |
| `src/crucible/recovery/strategy_selector.py` | `RecoveryStrategySelector`: failure + history → recovery strategy |
| `src/crucible/recovery/recovery_context.py` | `RecoveryContext`: wraps failure, attempt history, budgets |
| `src/crucible/recovery/result.py` | `RecoveryResult`: status, evidence, next_action from recovery |
| `src/crucible/recovery/recovery_executor.py` | `RecoveryExecutor`: invokes LLM for each recovery type |
| `tests/recovery/test_strategy_selector.py` | Test: each failure class maps to correct strategy |
| `tests/recovery/test_recovery_executor.py` | Test: recovery executor invokes LLM correctly |

### Exit Criteria

- [ ] RecoveryStrategySelector implements full mapping from failure to strategy
- [ ] RecoveryExecutor can invoke LLM for each recovery type
- [ ] RecoveryResult captures what LLM tried and outcome
- [ ] 20+ unit tests
- [ ] Reviewer agent passes

---

## Phase 2: Dependency Resolution

**Goal:** MISSING_DEPENDENCY triggers LLM to resolve, not user request.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/recovery/dep_resolver.py` | `DependencyResolver`: LLM analyzes, installs, verifies |
| `src/crucible/recovery/prompts.py` | Prompts for dep resolution (see spec Section 9.2) |
| `src/crucible/failures/taxonomy.py` | **Modify**: MISSING_DEPENDENCY → DEP_RESOLVE, not AWAITING_USER |
| `tests/recovery/test_dep_resolver.py` | Test: missing dependency triggers LLM install attempt |
| `tests/recovery/test_dep_resolver_e2e.py` | E2E: task with missing dep auto-resolves |

### Exit Criteria

- [ ] Missing dependency triggers LLM resolution, not user prompt
- [ ] LLM tries multiple install methods (uv, pip, etc.)
- [ ] Verification runs after install
- [ ] Evidence captured: what was tried, what worked
- [ ] 15+ tests
- [ ] Reviewer agent passes

---

## Phase 3: Environment Repair

**Goal:** ENVIRONMENT_BLOCK triggers LLM to fix environment, not do-nothing.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/recovery/env_repair.py` | `EnvironmentRepairer`: LLM diagnoses, fixes env issues |
| `src/crucible/recovery/prompts.py` | Add env repair prompts (see spec Section 9.1) |
| `src/crucible/failures/taxonomy.py` | **Modify**: ENVIRONMENT_BLOCK → ENV_REPAIR |
| `src/crucible/runtime/run_executor.py` | **Modify**: route ENVIRONMENT_BLOCK to recovery executor |
| `tests/recovery/test_env_repair.py` | Test: env block triggers LLM repair |
| `tests/recovery/test_env_repair_e2e.py` | E2E: astropy task auto-provisions via LLM |

### Exit Criteria

- [ ] Environment block triggers LLM repair, not do-nothing
- [ ] LLM tries different provisioning strategies
- [ ] Complex repos (astropy-style) auto-resolve
- [ ] Evidence captured: diagnosis, attempts, outcome
- [ ] 15+ tests
- [ ] Reviewer agent passes

---

## Phase 4: Creative Recovery

**Goal:** Repeated failures trigger fundamentally different approaches, not just more of the same.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/recovery/creative_repair.py` | `CreativeRepairExecutor`: LLM with "try different approach" prompt |
| `src/crucible/recovery/debug_analyzer.py` | `DebugAnalyzer`: LLM root-cause analysis |
| `src/crucible/recovery/prompts.py` | Add creative repair + debug prompts (see spec Section 9.3) |
| `src/crucible/failures/taxonomy.py` | **Modify**: Add CREATIVE_REPAIR, DEBUG_ANALYSIS actions |
| `tests/recovery/test_creative_repair.py` | Test: 2nd failure triggers creative approach |
| `tests/recovery/test_loop_creativity.py` | Test: repeated signature forces different strategy |

### Exit Criteria

- [ ] Same failure signature triggers creative repair
- [ ] Creative repair prompt explicitly asks for different approach
- [ ] Debug analyzer produces root-cause hypothesis with evidence refs
- [ ] Evidence tracks what approaches tried, prevents repetition
- [ ] 20+ tests
- [ ] Reviewer agent passes

---

## Phase 5: Budget Integration

**Goal:** Recovery attempts use separate budgets, don't consume main repair budget.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/policy/budgets.py` | **Modify**: Add recovery budgets (env_repair, dep_resolve, creative_repair, etc.) |
| `src/crucible/policy/budget_tracker.py` | **Modify**: Track recovery budgets separately |
| `src/crucible/failures/taxonomy.py` | **Modify**: Check budget availability before scheduling recovery |
| `tests/policy/test_recovery_budgets.py` | Test: recovery uses separate budget from repair |
| `tests/policy/test_budget_exhaustion.py` | Test: correct behavior when recovery budgets exhausted |

### Exit Criteria

- [ ] Recovery budgets defined and tracked
- [ ] Recovery attempts don't consume repair/debug budgets
- [ ] Circuit breaker accounts for recovery attempts
- [ ] Block only after recovery budgets exhausted
- [ ] 10+ tests
- [ ] Reviewer agent passes

---

## Phase 6: Evidence & Blocking

**Goal:** Blocked tasks include evidence of LLM exhaustion.

### Deliverables

| File | Description |
|------|-------------|
| `src/crucible/recovery/evidence.py` | `RecoveryEvidence`: what LLM tried, why each failed |
| `src/crucible/runtime/run_executor.py` | **Modify**: include recovery evidence in blocker packet |
| `src/crucible/runtime/status_emitter.py` | **Modify**: expose recovery attempt history |
| `tests/recovery/test_blocking_evidence.py` | Test: blocked task includes LLM attempt history |
| `tests/recovery/test_user_escalation.py` | Test: user only contacted when LLM exhausted |

### Exit Criteria

- [ ] Blocked tasks include recovery attempt evidence
- [ ] Evidence shows: what was tried, why it failed, what would be needed
- [ ] User escalation only after LLM exhaustion
- [ ] 10+ tests
- [ ] Reviewer agent passes

---

## Phase Dependencies

```
Phase 1 ──> Phase 2 ──> Phase 3 ──> Phase 4 ──> Phase 5 ──> Phase 6
                    │           │
                    └───────────┘
              (Phase 3 can start after Phase 2)
```

---

## Test Gating Strategy

| Phase | Min Tests | Key Coverage |
|-------|-----------|--------------|
| 1 | 20 | Strategy selection, executor interface |
| 2 | 15 | Dependency resolution flow |
| 3 | 15 | Environment repair flow |
| 4 | 20 | Creative recovery, loop detection |
| 5 | 10 | Budget tracking |
| 6 | 10 | Blocking evidence |

**Total minimum:** 90 tests

---

## Success Gates

1. **MISSING_DEPENDENCY no longer blocks** → triggers LLM resolution
2. **ENVIRONMENT_BLOCK no longer does nothing** → triggers LLM repair
3. **Repeated failure triggers creative approach** → not just more of the same
4. **Blocking requires LLM exhaustion** → evidence of what was tried
5. **User only contacted when truly stuck** → after all LLM strategies tried

---

## Next Step

Once approved, begin **Phase 1: Recovery Infrastructure**.
