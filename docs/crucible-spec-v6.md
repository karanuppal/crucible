# Crucible Specification v6: LLM-Augmented Autonomous Recovery

**Status:** Draft for review
**Date:** 2026-04-08
**Supersedes:** `docs/crucible-spec-v5.4.md`

---

## 1. Why v6 exists

v5.4 delivered a deterministic closed-loop execution harness. It classifies failures, selects next actions, and enforces budgets. This was necessary but insufficient.

The current gap: **the harness gives up too easily**.

When Crucible encounters:
- a missing dependency → asks user
- an environment block → schedules ENVIRONMENT_FIX which does nothing
- a validation failure → spawns repair, but the repair is just another LLM call with the same context

The fundamental problem is that v5.4 treats the LLM as a dumb worker that receives instructions, executes, and returns. It does not treat the LLM as a **problem-solving partner** that can:
- analyze a novel failure
- propose creative solutions
- try multiple strategies
- learn from failed attempts

The PRD says "sub-agent-first execution" but what we built is "sub-agent-as-worker" - the harness tells the LLM what to do, not what problem to solve.

**v6 exists to make the harness keep going through the LLM, not give up.**

---

## 2. Core Principle: Progressive Recovery

### 2.1 The recovery hierarchy

Every failure should trigger a **progressive recovery** sequence:

```
Level 1: Deterministic fix (code-owned)
    ↓ (if fails)
Level 2: LLM-assisted repair (analyze + propose + fix)
    ↓ (if fails)
Level 3: LLM with different strategy (change approach)
    ↓ (if fails)
Level 4: Escalate / block (only when LLM exhausted)
```

The harness should **never** skip to Level 4 without trying Levels 2-3.

### 2.2 What "keep going" means

- Environment fails to provision → LLM diagnoses and fixes
- Missing dependency detected → LLM identifies and installs
- Build fails → LLM analyzes error, proposes fix, retries
- Test fails → LLM understands the test, fixes the code, reruns
- Same failure recurs → LLM tries a fundamentally different approach

Only when the LLM has tried multiple distinct strategies and failed should the task block.

---

## 3. LLM-Augmented Recovery System

### 3.1 New recovery attempt types

v6 adds new attempt types that invoke the LLM as a problem-solver:

| Attempt Type | When Used | What the LLM Does |
|---|---|---|
| `env_repair` | Environment block | Diagnose env issue, fix tooling, reinstall deps |
| `dep_resolve` | Missing dependency | Identify package, install it, verify |
| `debug_analysis` | Repeated failure | Analyze root cause, propose fix |
| `creative_repair` | Standard repair failed | Try fundamentally different approach |
| `research_fix` | No obvious solution | Research the problem, implement solution |

### 3.2 Recovery strategy selector

A new `RecoveryStrategySelector` chooses which LLM strategy to try:

```python
def select_recovery_strategy(
    failure: FailureEvidencePacket,
    attempt_history: list[AttemptRecord],
    budgets_remaining: dict[str, int],
) -> RecoveryStrategy:
    # If deterministic fix available, try that first
    if failure.failure_class == FailureClass.ENVIRONMENT_BLOCK:
        if budgets_remaining["env_repair"] > 0:
            return RecoveryStrategy.LLM_ENV_REPAIR
    
    # If missing dependency, try dep resolution
    if failure.failure_class == FailureClass.MISSING_DEPENDENCY:
        if budgets_remaining["dep_resolve"] > 0:
            return RecoveryStrategy.LLM_DEP_RESOLVE
    
    # If validation failure, escalate through repair strategies
    if failure.failure_class == FailureClass.VALIDATION_FAILURE:
        prior_repairs = [a for a in attempt_history if a.attempt_type == AttemptType.REPAIR]
        if len(prior_repairs) >= 2:
            return RecoveryStrategy.LLM_CREATIVE_REPAIR
        return RecoveryStrategy.LLM_REPAIR
    
    # If same signature repeated, force debug analysis
    if _signature_repeated(failure, attempt_history):
        return RecoveryStrategy.LLM_DEBUG_ANALYSIS
    
    return RecoveryStrategy.LLM_REPAIR
```

### 3.3 LLM recovery prompt contract

When invoking the LLM for recovery, the harness provides:

```
## Failure Context
- What failed: {criterion_id}
- Error: {error_output}
- Evidence: {evidence_refs}

## Attempt History
{prior_attempts_summary}

## Recovery Goal
Solve this problem. You may:
1. Analyze the failure
2. Propose a fix
3. Execute the fix
4. Verify it works

## Constraints
- Do NOT ask the user for help
- Try multiple approaches if first fails
- Document what you tried and why
- If you cannot solve, explain what would be needed
```

The LLM is told: "solve this" not "do this specific thing."

---

## 4. Specific Recovery Behaviors

### 4.1 Dependency Resolution (MISSING_DEPENDENCY)

Current behavior (bad):
```
failure_class = MISSING_DEPENDENCY
next_action = AWAITING_USER
Task blocks: "How would you like to provide it?"
```

v6 behavior (good):
```
1. LLM analyzes: "No module named pytest"
2. LLM identifies: package = pytest
3. LLM proposes: pip install pytest
4. LLM executes: install in venv
5. LLM verifies: re-run test
6. If fails: try alternative (uv add pytest)
7. If still fails: escalate with evidence
```

The task should **never** block on missing dependency without the LLM trying to resolve it.

### 4.2 Environment Repair (ENVIRONMENT_BLOCK)

Current behavior (bad):
```
1. ensure_existing_repo_environment() runs
2. Creates .venv, runs uv sync
3. If astropy-style complex deps → fails silently
4. failure_class = ENVIRONMENT_BLOCK
5. next_action = ENVIRONMENT_FIX (does nothing)
6. Task blocks
```

v6 behavior (good):
```
1. Detect environment provision failure
2. LLM analyzes: "astropy uses tox, not uv sync"
3. LLM proposes: "install via tox -e py3 --notest"
4. LLM executes: install with correct tool
5. LLM verifies: run test
6. If fails: try pip install with requirements files
7. If still fails: try manual dependency resolution
8. Only block if all strategies exhausted
```

### 4.3 Validation Failure (VALIDATION_FAILURE)

Current behavior (bad):
```
1. Build attempt runs
2. Test fails
3. failure_class = VALIDATION_FAILURE
4. next_action = REPAIR
5. Spawns repair attempt with "fix the test"
6. Same LLM gets same context, same failure mode
```

v6 behavior (good):
```
1. Build fails test
2. LLM analyzes failure in depth
3. LLM proposes fix (different from prior attempts)
4. LLM executes fix
5. LLM verifies test passes
6. If fails: LLM tries different approach
7. Track what approaches tried, don't repeat
```

### 4.4 Loop Detection → Creative Recovery

When the same failure signature repeats:
- v5.4: trips circuit breaker, blocks task
- v6: forces LLM debug_analysis with explicit instruction "try a fundamentally different approach"

---

## 5. Budget Model for v6

### 5.1 Recovery budgets (extends v5.4)

| Budget | Purpose | Default |
|---|---|---|
| `env_repair_budget` | LLM environment fix attempts | 3 |
| `dep_resolve_budget` | LLM dependency resolution attempts | 3 |
| `creative_repair_budget` | Fundamentally different repair approaches | 2 |
| `debug_analysis_budget` | LLM root-cause analysis attempts | 2 |
| `research_fix_budget` | LLM research + implementation | 2 |

These are **separate** from build/repair/debug budgets. Using LLM recovery does not consume the main repair budget.

### 5.2 Budget exhaustion rules

- If `env_repair_budget` exhausted → try `dep_resolve` as fallback
- If all LLM recovery budgets exhausted → block with evidence
- **Never** block while any LLM strategy remains untried

---

## 6. The "No Give Up" Invariant

### 6.1 Forbidden blocking conditions

The following **must not** cause immediate blocking:
- `MISSING_DEPENDENCY` without LLM resolution attempt
- `ENVIRONMENT_BLOCK` without LLM repair attempt
- `VALIDATION_FAILURE` without LLM-assisted repair
- Repeated failure without LLM debug_analysis

### 6.2 Required LLM intervention before block

Before any task reaches `blocked` state, the following must be true:
1. At least one LLM recovery attempt was made for the specific failure
2. The LLM documented what it tried and why it failed
3. Either:
   a. All LLM recovery budgets exhausted, OR
   b. The failure is truly unambiguous (ambiguity_block)

### 6.3 Evidence requirement for blocking

A blocked task must include:
```
- What deterministic approaches were tried
- What LLM recovery strategies were attempted
- Why each failed
- What would be needed to unblock
```

This ensures the user gets useful information, not just "I gave up."

---

## 7. Implementation Architecture

### 7.1 New components

```
src/crucible/recovery/
├── __init__.py
├── strategy_selector.py    # Chooses LLM recovery strategy
├── env_repair.py           # LLM-driven environment fix
├── dep_resolver.py         # LLM-driven dependency resolution
├── creative_repair.py      # LLM with different approach
├── debug_analyzer.py       # LLM root-cause analysis
└── recovery_executor.py    # Executes recovery attempts
```

### 7.2 Modified components

- `next_action_selector.py`: Add LLM recovery actions
- `run_executor.py`: Route to recovery executor instead of blocking
- `failure/taxonomy.py`: Map failures to LLM recovery, not user request

### 7.3 Recovery executor interface

```python
class RecoveryExecutor:
    async def execute_recovery(
        self,
        strategy: RecoveryStrategy,
        failure: FailureEvidencePacket,
        context: RecoveryContext,
    ) -> RecoveryResult:
        """Execute LLM-driven recovery attempt.
        
        Returns:
            RecoveryResult with:
            - status: attempted | succeeded | failed | exhausted
            - evidence: what the LLM did
            - next_action: continue | block | escalate
        """
```

---

## 8. State Machine Updates

### 8.1 New attempt types

```python
class AttemptType(Enum):
    BUILD = "build"
    REPAIR = "repair"
    DEBUG = "debug"
    REVIEW = "review"
    SALVAGE = "integrate"
    REVALIDATE = "revalidate"
    # v6 additions
    ENV_REPAIR = "env_repair"           # LLM fixes environment
    DEP_RESOLVE = "dep_resolve"         # LLM resolves dependency
    CREATIVE_REPAIR = "creative_repair" # LLM tries different approach
    DEBUG_ANALYSIS = "debug_analysis"   # LLM analyzes root cause
    RESEARCH_FIX = "research_fix"       # LLM researches and implements
```

### 8.2 State transition updates

```text
build.validated_fail
  -> classify failure
     -> ENV_REPAIR (if environment_block)
     -> DEP_RESOLVE (if missing_dependency)
     -> REPAIR (if validation_failure, first time)
     -> CREATIVE_REPAIR (if validation_failure, 2nd try)
     -> DEBUG_ANALYSIS (if signature repeated)

env_repair.completed / dep_resolve.completed
  -> re-validate original criterion
     -> pass: continue normal flow
     -> fail: retry with next strategy

creative_repair.completed
  -> if passes: continue
  -> if fails: DEP_RESOLVE (if dependency suspected)
  -> if fails: block (LLM exhausted)
```

---

## 9. LLM Prompt Engineering for Recovery

### 9.1 Environment repair prompt

```
You are debugging an environment setup failure.

## The Problem
{error_output}

## What Was Tried
{commands_already_run}

## Your Job
1. Analyze what specifically failed
2. Identify the root cause
3. Fix the issue
4. Verify the fix works

## Important
- Do NOT simply repeat what was tried
- If the original approach is wrong, try a different one
- For Python projects, consider: uv pip install, pip install, tox, manual install
- Document each attempt and why it succeeded or failed
- Keep trying until you succeed or exhaust all reasonable approaches
```

### 9.2 Dependency resolution prompt

```
A Python dependency is missing.

## The Error
{error_output}

## What We Tried
{install_commands_already_run}

## Your Job
1. Identify the exact package needed
2. Install it correctly
3. Verify the original command now works

## Important
- Try multiple install methods (uv, pip, conda)
- Check if the package has a different name
- Verify version compatibility
- Document each attempt
```

### 9.3 Creative repair prompt

```
Previous repair attempts failed to fix this issue.

## Failure History
{attempt_history}

## The Problem
{current_failure}

## Your Job
The previous approaches did not work. You MUST try something fundamentally different.

1. Re-analyze the problem from first principles
2. Consider: is the diagnosis correct?
3. Consider: is there a completely different solution?
4. Implement a novel approach
5. Verify it works

## Critical
- Do NOT repeat the same approaches
- If you find yourself wanting to try something similar, stop and think of something else
- Document why this approach is different from prior attempts
```

---

## 10. Example: astropy Task with v6

### Before (v5.4 - gives up)
```
1. Clone astropy at commit
2. Run ensure_existing_repo_environment()
   - Creates .venv
   - Runs uv sync (astropy has no standard deps - fails)
3. Run test: "No module named pytest"
4. Classify: MISSING_DEPENDENCY
5. Next action: AWAITING_USER
6. Task blocks: "How would you like to provide it?"
```

### After (v6 - keeps going)
```
1. Clone astropy at commit
2. Run ensure_existing_repo_environment()
   - Creates .venv
   - Runs uv sync (fails: no standard deps)
3. Classify: MISSING_DEPENDENCY (pytest not installed)
4. Recovery strategy: LLM_DEP_RESOLVE
5. LLM analyzes: "astropy uses tox, not pip. Need to install via tox or manually"
6. LLM tries: "uv pip install pytest"
7. Verify: test still fails (other deps missing)
8. LLM tries: "pip install -r pip-requirements"
9. Verify: test runs, fails on actual bug
10. Normal repair flow continues...
```

The key difference: **the harness kept going instead of asking the user.**

---

## 11. Migration from v5.4

### 11.1 What v6 preserves
- Deterministic state machine
- Budget tracking
- Evidence persistence
- Workspace lineage
- Reviewer gate

### 11.2 What v6 changes
- `MISSING_DEPENDENCY` no longer maps to `AWAITING_USER`
- `ENVIRONMENT_BLOCK` no longer maps to do-nothing `ENVIRONMENT_FIX`
- Every failure triggers LLM recovery before blocking
- Blocking requires evidence of LLM exhaustion
- New recovery attempt types

### 11.3 Migration path

#### Phase A: Recovery infrastructure
- Add `recovery/` module
- Add `RecoveryStrategySelector`
- Add recovery executor

#### Phase B: Failure mapping update
- Change `MISSING_DEPENDENCY` → `DEP_RESOLVE`
- Change `ENVIRONMENT_BLOCK` → `ENV_REPAIR`
- Update next_action_selector

#### Phase C: Prompt engineering
- Write recovery prompts for each type
- Add evidence capture to recovery attempts

#### Phase D: Budget integration
- Add recovery budgets
- Update circuit breaker

#### Phase E: Testing
- Test: missing dependency triggers LLM resolution
- Test: environment block triggers LLM repair
- Test: repeated failure triggers creative repair
- Test: LLM exhaustion leads to proper block with evidence

---

## 12. Success Criteria

v6 is complete when:
1. **No auto-block on recoverable failures**: Missing dependency, environment block, validation failure all trigger LLM recovery first
2. **Evidence of LLM effort**: Every block includes what the LLM tried
3. **Creative recovery works**: Same failure signature triggers different approaches
4. **User only contacted when truly stuck**: Only after LLM exhausts all strategies

---

## 13. Summary

v6 fixes the core usability problem: **the harness gave up too easily**.

The principle: "keep the LLM going in a fixed loop, get creative when deterministic things fail."

- Deterministic where possible (state machine, budgets, evidence)
- LLM-augmented when needed (recovery attempts)
- Block only when LLM exhausted (with evidence)

This makes Crucible actually useful for real software tasks, not just toy problems.
