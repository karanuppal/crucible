# Agentic Coding Toolkit — Architecture v4.6.2

**Status:** Production spec — engine-agnostic variant
**Changes from v4.6.1:** Removed Claude Code / Codex harness assumption. This version assumes raw model execution (Anthropic Opus/Sonnet, OpenAI GPT-5.4, MiniMax, Gemini, etc.) through direct tool access — no coding-agent harness wrapping the model. See `v4.6.2-review-notes.md` for a full diff analysis of what changes and what doesn't.

**Key question this version answers:** Does the governance layer change when the execution engine is a general-purpose model with standard tools (read/write/exec) instead of a specialized coding harness?

**Answer:** The governance layer is ~90% identical. What changes is dispatch, tool access patterns, and context management. The state machine, failure taxonomy, rejection ledger, circuit breakers, contract validation, review protocol, and artifact chain are all engine-agnostic by design.

---

## 1. Overview

This system enables MillieClaw (Opus 4.6, main agent) to build software autonomously on Mac Mini M4. It wraps **any model** — whether accessed through a coding harness (Claude Code, Codex) or directly as a raw model (Opus, GPT-5.4, Sonnet, MiniMax, Gemini) — in a governance layer: spec-first workflow, deterministic state machine, quality gates, failure taxonomy, and cross-project memory.

**This version (v4.6.2) assumes no coding harness.** The executing model has access to standard tools (read/write/exec/browser/web_search) but not the shell-level autonomy that Claude Code or Codex provide. MillieClaw IS the orchestrator AND may be the executor, or may spawn sub-agents that are also raw models.

The unique value is not in the agents themselves — it's in the harness that orchestrates them. The same model scores 45–57% on SWE-bench depending on harness. Our governance layer IS the harness. In this variant, the governance layer also compensates for capabilities that coding harnesses provide natively (autonomous file exploration, iterative edit-test loops, background process management).

---

## 2. Design Principles

Every principle traces to a real failure.

- **MillieClaw = brain, code = spine.** Strategy decisions are MillieClaw's. Bookkeeping is deterministic code.
- **Deterministic gates, not vibes.** `npm test` returns 0 or 1. "This looks good" is not a gate.
- **Spec is the source of truth.** Sub-agents read the spec file — not your summary, not your interpretation.
- **Preflight before build.** Never build in a broken environment or on an ambiguous spec.
- **Investigate → Reproduce → Fix → Verify.** Every bug fix starts with tracing the data flow, then a failing test, then the fix, then proof it passes. (Details in §4.6)
- **Classify failures, don't count retries.** "Spec ambiguity" triggers a different response than "environment failure." (§7)
- **Strongest available validation.** Run the highest contract validation level the project supports. (§4.8)
- **Human on the loop, not in the loop.** Karan approves specs and handles escalations. Everything between is autonomous.
- **Fix, don't report.** Monitoring detects a problem → first action is fix it.
- **Survive session death.** All build state is on disk. Recovery is automatic.
- **Simple beats complete.** A working 200-line state machine beats a designed-but-unbuilt 2000-line orchestrator.
- **Circuit breaker over retry count.** Three independent failure signals before stopping — not just "attempt 3/5 failed." (§4.10)
- **Sandbox before apply.** Test changes in isolation before touching the real branch. (§4.12)
- **Tiered context, not full context.** HOT (current task), WARM (related files), COLD (searchable via QMD). (§8)
- **Memory is files.** If it's not written down, it doesn't exist.
- **Use what exists.** The coding-agent Skill, ACP runtime, Claude Code's native capabilities — use them. Don't rebuild.
- **Artifacts chain explicitly.** Each phase names what it produces and what the next phase consumes. No summaries in between. (§14)

---

## 3. The Stack

```
Karan (human) — approves specs, handles escalations
  │
MillieClaw (Opus 4.6) — strategy, decomposition, failure handling, orchestration
  │
  ├── build_loop.py (deterministic state machine) — bookkeeping, persistence, enforcement
  ├── Sub-agent spawns (sessions_spawn) — raw model execution in isolated sessions
  ├── Direct tools — read/write/exec/browser/web_search/web_fetch
  └── Memory system — QMD, Obsidian, lessons.jsonl, daily logs
```

### Division of Labor

| Responsibility | Owner |
|---|---|
| What to build | Karan |
| How to decompose, when to escalate/retry/abandon | MillieClaw |
| Counting retries, enforcing budgets, persisting state, classifying failures | `build_loop.py` |
| Writing code | Any model via sub-agent spawn (or MillieClaw inline for small tasks) |
| Reviewing code | Separate sub-agent spawn (different model preferred) |
| Running gates | Shell commands (deterministic, observable) |

### Engine Selection

Without a coding harness, model selection is purely about capability matching:

| Task | Model Guidance |
|---|---|
| Complex implementation (multi-file, algorithmic) | Strongest available (Opus 4.6, GPT-5.4) |
| Simple implementation (config, docs, single-file) | Cost-efficient model (Sonnet, Haiku, Mini) |
| Code review | Different model than builder (reduces shared blind spots) |
| Security review (Tier 2+) | Strongest available |
| Parallel independent tasks | Multiple sub-agent spawns on separate worktrees |

**Key difference from v4.6.1:** No dependency on any specific CLI tool (`claude`, `codex`). Any model accessible through OpenClaw's model routing or sub-agent spawning can serve as the execution engine.

---

## 4. The Build Loop

### 4.0 Pre-Build Reading (Every Coding Session)

```
1. Read CODING-BEST-PRACTICES.md (mandatory, no exceptions)
2. Read the project's knowledge file (knowledge/projects/<project>.md)
3. If resuming: read the spec, check git status, run tests to know current state
```

### 4.1 Preflight

**Consumes:** Repo state, env vars → **Produces:** `preflight.json`

```
PREFLIGHT CHECKLIST (run as script — tools/build-loop/preflight.sh)
════════════════════════════════════════════════════════════════════
□ 1. Repository: clean working tree, on feature branch (NEVER main), up-to-date with main
□ 2. Dependencies: npm ci / pip install succeeds, no lockfile conflicts
□ 3. Baseline tests: existing suite passes, record pass count
□ 4. Baseline lint + typecheck: passes (or record existing violations)
□ 5. Secrets & external deps: env vars present, services reachable, vault credentials available
□ 6. Spec completeness: passes ambiguity detection (§4.2)

RESULT: preflight.json with status per check
ANY HARD FAILURE → STOP. Fix environment first.
```

**Environment failures don't consume task retry budget.** The state machine tracks them separately.

### 4.2 Spec Ambiguity Detection

**Consumes:** `preflight.json`, Karan's feature description → **Produces:** Ambiguity-resolved spec draft or questions for Karan

Before decomposition, check the spec for:
- Undefined terms with multiple interpretations
- Missing acceptance criteria (features without measurable verification)
- Unclear scope boundaries ("and related functionality", "etc.")
- Implicit dependencies (external services, APIs, data not mentioned)
- Contradictions

**If ambiguity found:** Compile specific questions with proposed options (A/B/C). Ask Karan **once** — not "is the spec clear?" but "Term X could mean A or B. Which?" Update spec with answers, then proceed.

### 4.3 Spec Phase

**Consumes:** Validated scope from §4.2 → **Produces:** Spec file in `docs/` or project repo

```markdown
# Feature: [Name]
## Version: [X.Y]

## Problem
[What problem, who has it, what happens without this]

## Success Criteria
- [ ] Criterion 1 (measurable, verifiable command)
- [ ] Criterion 2

## User Journeys
### Journey 1: [Name]
- Given: [precondition]
- When: [action]
- Then: [expected outcome with specific verification]

## API Contracts
[Exact function signatures — verified against real SDK before implementation]

## Tasks
1. [Task] — [exit criterion] — [verification command]

## Verification Triple (per task)
Each task defines: (a) what to build, (b) how to verify, (c) what failure looks like

## Contract Validation Levels Available
[Which of the 5 levels (§4.8) can be run]

## Risk Tier: [0-3]
```

**Gate:** Karan approves the spec. No implementation starts without approval.

### 4.4 Task Decomposition

**Consumes:** Approved spec file → **Produces:** Task list with verification triples, stored in build state

Rules:
- Each task names an exact verification command
- Each task modifies ≤5 files (more → split it)
- Dependencies are explicit and acyclic
- Every API contract verified against real SDK types BEFORE implementation
- Size estimate: **S** (1 file), **M** (2-3 files), **L** (4-5 files)
- **Auto-split trigger:** >5 files or >2 iterations to pass basic tests → split before continuing

**Per-task verification triple** (mandatory):
- **(a) What to build** — deliverables from spec
- **(b) How to verify** — exact commands that prove correctness
- **(c) What failure looks like** — specific error/output that means it's broken

### 4.5 The Three-Pass Build Loop

Every task goes through: build → validate contracts → independent review.

```
PREFLIGHT PASSED
     │
     ▼
┌── PASS 1: BUILD ──────────────────────────────┐
│  Spawn coding agent with task prompt           │
│  Build + unit test + self-review               │
│  Bug fixes: MANDATORY investigate→reproduce→   │
│    fix→verify (§4.6)                           │
│  Gate: tests pass? lint clean?                 │
│    NO → retry (within budget)                  │
│    YES ↓                                       │
│  PRODUCES: code changes + test results         │
└────────────────────────────────────────────────┘
     │
     ▼
┌── PASS 2: CONTRACT VALIDATION ────────────────┐
│  CONSUMES: code changes from Pass 1            │
│  Run strongest available level (§4.8)          │
│  Deterministic — no LLM tokens spent           │
│  Gate: contracts satisfied?                    │
│    NO → retry │ YES ↓                          │
│  PRODUCES: contract validation report          │
└────────────────────────────────────────────────┘
     │
     ▼
┌── PASS 3: POST-BUILD VALIDATION ──────────────┐
│  CONSUMES: spec + diff + test output +         │
│    contract validation report                  │
│  Independent reviewer (§4.9)                   │
│  Deterministic audit checklist                 │
│  Mutation testing for test quality             │
│  Browser QA (if spec has UI journeys)          │
│  Security review w/ OWASP+STRIDE (Tier 2+)    │
│  Gate: all checks pass?                        │
│    NO → back to Pass 1 │ YES ↓                 │
│  PRODUCES: review verdict + audit report       │
└────────────────────────────────────────────────┘
     │
     ▼
TASK DONE → next task
     │
(after all tasks)
     ▼
┌── CROSS-TASK INTEGRATION ─────────────────────┐
│  Full test suite, cross-task conflict check    │
│  (file overlap, shared state, API breaks)      │
│    NO → identify conflicts, fix                │
│    YES → SHIP (§4.14) → LEARN (§4.15)         │
└────────────────────────────────────────────────┘
```

### 4.6 Bug Fix Protocol: Investigate → Reproduce → Fix → Verify

**Iron law: no fixes without investigation.** Before writing any fix, trace the actual data flow. Hypothesis → evidence → fix, not guess → hope → retry.

```
1. INVESTIGATE: Trace the data flow through the bug
   - Add instrumentation at key points
   - Observe actual vs expected behavior
   - Form hypothesis FROM evidence, not from reading code
2. LOCATE: Symbol-level fault localization (suspect functions/classes, not just files)
3. REPRODUCE: Write a test that FAILS with current (buggy) code
   - Must be deterministic (no intermittent passes)
   - Encodes EXPECTED behavior, not current broken behavior
4. FIX: Change the code (minimal patch)
5. VERIFY: Reproducing test now PASSES + full suite has no regressions
   - Check adjacent callsites for similar issues
   - Reproducing test stays in suite permanently
```

**Three-strike rule:** If three fix attempts fail, your mental model is wrong. Stop — go one level deeper. Check the actual API contract, the real data flow, the runtime behavior.

**Key examples:**
- **Credential Vault hooks:** 7/7 hook signatures wrong despite 536 passing tests — mocks encoded assumptions, not reality. Reproduce against real SDK types would have caught it.
- **Hostname key derivation:** `os.hostname()` in key derivation → hostname drifted via mDNS → all encrypted files unreadable. Investigation-first traced the actual data flow.

### 4.7 Iteration Budgets

| Task Size | Pass 1 | Pass 2 | Pass 3 | Total Max | Wall Clock |
|---|---|---|---|---|---|
| S (1 file) | 2 | 1 | 1 | 4 | 30 min |
| M (2-3 files) | 3 | 2 | 2 | 7 | 90 min |
| L (4-5 files) | 4 | 3 | 2 | 9 | 180 min |

**No-progress detection:** Same tests fail with same error after 2 consecutive iterations → STOP. Classify failure (§7) and escalate.

### 4.8 Graded Contract Validation (Pass 2)

Verify code works against the REAL system, not just mocks. Five levels, escalating strength:

| Level | What It Checks | Example |
|-------|---------------|---------|
| **L1** | Real type imports compile | `tsc --noEmit` with real SDK imports |
| **L2** | Generated client/SDK stubs compile | Build against OpenAPI/protobuf types |
| **L3** | Golden request/response fixtures validate | Recorded real API interactions as test fixtures |
| **L4** | Local integration harness passes | Local instance of target system |
| **L5** | Staging smoke test | Deploy to staging, run end-to-end |

**Rules:**
- Every level is a concrete command returning pass/fail. No LLM involved.
- Project's knowledge file declares availability: `contract_validation: {L1: "tsc --noEmit", L3: "pytest tests/fixtures/"}`
- Build loop runs the strongest available level.
- If no levels available, Pass 2 is skipped (but document why).

### 4.9 Post-Build Validation (Pass 3)

**Consumes:** Spec file, git diff, test output, contract validation report → **Produces:** Review verdict + audit report

**Deterministic audit:** Public API changed → docs updated? New deps → justified? Migration → script included? Rollback path? Logging added? Test count ≥ baseline? Files ≤5? No secrets in diff? Bug fix → reproduce test present?

**Mutation testing:** Mutate changed code after tests pass. Tests still pass → vacuous tests → rework.

**Anti-vacuity:** If implementation were deleted, tests must fail. `assert True` is rejected.

**Browser QA (for projects with UI):**
When the spec defines user journeys with a web/UI interface:
1. Open a real browser (OpenClaw `browser` tool — not headless Playwright)
2. Walk through each user journey defined in the spec
3. Screenshot key states; compare against spec's "Then" clauses
4. Deviations → findings with screenshot evidence

**Review tiers:**

| Tier | Reviewer Personas |
|------|------------------|
| **0** | Deterministic audit checklist only (no LLM reviewer) |
| **1** | **Spec Compliance Reviewer** — reads spec independently, generates own checklist, verifies every criterion. Must produce: one likely escaped defect, one untested path. |
| **2** | Spec Compliance + **Adversarial Security Reviewer** — applies OWASP Top 10 + STRIDE (§6.3). System prompt: "Your job is to BREAK this code." |
| **3** | Same as Tier 2. **Karan checkpoint blocks shipping only**, not building. |

**Anti-rubber-stamp rules:**
- Each reviewer persona is a SEPARATE agent spawn with NO shared context from the builder.
- Reviewers receive only: spec file, git diff, test results. Never the builder's reasoning.
- **Cross-engine review (strongest):** Different model for reviewer than builder. Different biases = harder to rubber-stamp.
- Zero findings is suspicious — reviewer must explain why, citing specific tests.

### 4.10 Circuit Breaker

Three independent failure signals per task:

| Signal | Threshold | Action |
|---|---|---|
| **No-progress** | 2 loops with no file changes or same test failures | HALT |
| **Same-error** | 3 loops with identical error signature | HALT + classify |
| **Output-decline** | Agent output quality drops >70% | HALT + escalate |

Any single signal triggers halt + classification. Replaces naive retry counting.

### 4.11 Rejection Ledger

For every failed approach, persist in state machine:

```json
{
  "task_id": "task-003",
  "rejections": [{
    "attempt": 1,
    "patch_summary": "Added null check in parseConfig()",
    "failure_type": "same_error",
    "validator_output": "TypeError at line 42",
    "why_rejected": "Null check in wrong branch — error from async callback",
    "lesson": "Bug is in async callback chain, not sync initialization"
  }]
}
```

Injected into subsequent retry prompts. Persisted across session restarts.

### 4.12 Sandbox-Before-Apply

- All work on feature branches. **NEVER on main.**
- Each task is a commit on the feature branch.
- Failed builds leave previous successful tasks intact.
- `git checkout main` always returns to known-good state.
- PR created only after all tasks + cross-task integration passes.

### 4.13 Flaky Test Protocol

Test fails → rerun. Passes on rerun → FLAKY → quarantine (tracked, doesn't block, appears in report). Fails on rerun → DETERMINISTIC → normal retry flow.

### 4.14 Ship Checklist

```
SHIP CHECKLIST
═══════════════
□ 1. Sync: merge/rebase main into feature branch — resolve conflicts
□ 2. Full suite: run ALL tests — must pass
□ 3. Lint + typecheck: clean on merged result
□ 4. Coverage delta: ≥ baseline (from preflight.json), new code ≥80% or justified
□ 5. Secrets audit: no API keys, tokens, passwords in diff or logs
□ 6. Spec criteria: re-read every success criterion, check off with evidence
□ 7. Docs: README, API docs, CHANGELOG updated if applicable
□ 8. Commit hygiene: squash fixups, meaningful messages
□ 9. Push + PR: create PR with summary linking to spec
□ 10. CI green: wait for CI — fix immediately if it fails
```

All 10 items checked before notifying Karan "done."

### 4.15 Learn

**Consumes:** Completed build → **Produces:** Updated memory

1. Lessons → `lessons.jsonl` (what went wrong, what worked, what to do differently)
2. Update project knowledge file (`knowledge/projects/<project>.md`)
3. Log cost → `memory/build-costs.jsonl`
4. Update daily log → `memory/YYYY-MM-DD.md`

### 4.16 Updates to Karan

- **Start:** "Starting N-task build. Estimated: [X hours]."
- **Per task:** "Task 2/4 complete: [summary]."
- **Blocker:** "Task 3 stuck. [Failure class]. Options: A/B/C?"
- **Done:** "All complete. PR at [link]."

---

## 5. State Machine

### 5.1 Design Principles

- **Deterministic** — same input → same state transition
- **Persistent** — survives session death, gateway restart, machine reboot
- **Resumable** — picks up exactly where it left off
- **Observable** — current state always queryable
- **MillieClaw-driven** — state machine doesn't make strategic decisions; MillieClaw reads state and issues commands

### 5.2 Schema

```python
@dataclass
class BuildState:
    build_id: str              # uuid
    spec_path: str
    repo_path: str
    branch: str
    risk_tier: int             # 0-3
    created_at: str            # ISO timestamp
    updated_at: str
    phase: str                 # preflight | decompose | building | integrating | shipping | done | failed | escalated
    preflight: PreflightState
    tasks: list[TaskState]
    current_task_idx: int
    total_tokens_used: int
    total_cost_usd: float
    token_budget: int
    cost_budget_usd: float
    events: list[BuildEvent]   # append-only log

@dataclass
class TaskState:
    task_id: str
    description: str
    size: str                  # S | M | L
    verification_triple: dict  # {build, verify, failure_looks_like}
    allowed_files: list[str]
    verification_cmd: str
    is_bug_fix: bool
    current_pass: str          # build | contract | validation | done | failed
    build_attempts: int
    contract_attempts: int
    validation_attempts: int
    last_build_result: PassResult | None
    last_contract_result: PassResult | None
    last_validation_result: PassResult | None
    # Bug fix tracking
    reproduce_test_written: bool
    reproduce_test_failed_before_fix: bool
    reproduce_test_passed_after_fix: bool
    # Circuit breaker
    no_progress_count: int
    same_error_count: int
    last_error_signature: str | None
    # Rejection ledger
    rejections: list[Rejection]
    # Failure
    failure_class: str | None
    failure_detail: str | None

@dataclass
class PassResult:
    status: str    # pass | fail | flaky
    output: str
    timestamp: str
    tokens_used: int
    duration_seconds: int
    error_signature: str | None

@dataclass
class Rejection:
    attempt: int
    patch_summary: str
    files_touched: list[str]
    failure_type: str
    validator_output: str
    why_rejected: str
    lesson: str

@dataclass
class BuildEvent:
    timestamp: str
    event_type: str  # phase_change | pass_start | pass_end | retry | escalation | budget_warning | circuit_break
    detail: str
```

### 5.3 State Transitions

```
preflight ──→ decompose ──→ building ──→ integrating ──→ shipping ──→ done
    │              │            │              │              │
    ▼              ▼            ▼              ▼              ▼
  failed        failed       failed         failed        failed
  (env)       (ambiguity)  (exhausted)    (conflicts)   (ship check)
                               │
                               ▼
                           escalated
                         (with taxonomy)

Within a task (building phase):
  build ──→ contract ──→ validation ──→ done
    │          │            │
    ▼          ▼            ▼
  retry      retry     back to build
  (budget?)  (budget?)  (with findings)
```

### 5.4 Persistence

```
tools/build-loop/
├── build_loop.py
├── test_build_loop.py
└── states/{build_id}.json   # written after every transition
```

### 5.5 Key Operations

```python
state = build_loop.start_build(spec_path, repo_path, branch, risk_tier, token_budget, cost_budget)
state = build_loop.run_preflight(build_id, preflight_results)
state = build_loop.set_tasks(build_id, tasks)
state = build_loop.record_pass_result(build_id, task_id, pass_name, result)
state = build_loop.record_reproduce_step(build_id, task_id, step, success)
state = build_loop.record_rejection(build_id, task_id, rejection)
next_action = build_loop.next_action(build_id)
# Returns: RunPass | Retry | Escalate | Integrate | Ship | Done | BudgetExceeded | CircuitBreak
is_stuck = build_loop.check_no_progress(build_id, task_id)
state = build_loop.classify_failure(build_id, task_id, failure_class, detail)
state = build_loop.load(build_id)  # resume after interruption
```

### 5.6 Usage Flow

`start_build` → `run_preflight` → (fix env if needed) → ambiguity check → spec approval → `set_tasks` → loop on `next_action`: RunPass (spawn agent), Retry (+ rejection ledger), CircuitBreak (classify + escalate), Integrate (cross-task), Ship (§4.14 checklist), Done (learn §4.15), BudgetExceeded (stop). Update Karan after each task.

---

## 6. Prompt Templates

### 6.1 Task Prompt

```
You are working in: {repo_path} (branch: {branch})
Read the spec at {spec_path} — the ENTIRE file, not a summary.

Your task: {task_description}
Allowed files: {allowed_files}
Task size: {size} (budget: {max_build_attempts} build iterations)

AVAILABLE TOOLS: You have access to read, write, edit, and exec tools.
Use exec to run tests, lint, type-checking, and any shell commands.
Use read to explore files. Use write/edit to modify code.

CONTEXT — these files are pre-loaded for you:
{pre_loaded_file_contents_for_HOT_tier}

ADDITIONAL FILES (read these if needed):
- WARM: {related_files}
- Search via exec("grep -r 'term' {repo_path}") if you need to find something not listed

BEFORE YOU START:
1. List every deliverable from the spec for this task.
2. List the verification commands.

{if is_bug_fix}
MANDATORY: INVESTIGATE → LOCATE → REPRODUCE → PATCH → VALIDATE
3. Trace the data flow through the bug — add instrumentation, observe actual behavior.
4. Locate suspect symbols (functions/classes, not just files).
5. Write a test that REPRODUCES the bug (must FAIL with current code).
6. Show the test failing.
7. Fix the code (minimal patch).
8. Show the reproducing test passing.
9. Check adjacent callsites for similar issues.
If 3 fix attempts fail: STOP. Your mental model is wrong. Re-investigate from scratch.
{else}
3. Write tests FIRST (from spec criteria, not from your implementation).
4. Implement.
{endif}
5. Run tests via exec — fix until green.
6. Run lint via exec — fix until clean.
7. Run full test suite via exec — fix any regressions.

EDIT-TEST LOOP:
When tests fail, do NOT just guess at fixes. Read the error output carefully,
trace the failure, edit the specific code, and re-run. You have full tool access
to iterate — use it. Each edit→test cycle should be one tool call sequence.

CODE REQUIREMENTS:
- Every new public function: parameter validation assertions
- Every new API endpoint: request/response logging
- Every error path: structured logging with context
- No secrets, no hardcoded paths, no TODO/FIXME without tracking issue
- Subprocess-spawning code: cleanup on all exit paths (try/finally, SIGTERM/SIGINT)

REJECTED APPROACHES (do NOT retry these):
{rejection_ledger_entries}

CONSTRAINTS FROM PRIOR BUILDS:
{injected_lessons}

BEFORE DECLARING DONE:
8. Re-read the spec section for this task.
9. Check each deliverable against what you built.
10. Run ALL verification commands via exec and show raw output.

OUTPUT FORMAT:
TASK_COMPLETE
Files modified: [list]
Tests added: [count]
All tests passing: [yes/no]
{if is_bug_fix}Reproduce test: [name] | Failed before: [y/n] | Passed after: [y/n]{endif}
Verification output: [raw output]
```

**v4.6.2 changes from v4.6.1 task prompt:**
- Added explicit "AVAILABLE TOOLS" section — harness agents know their tools implicitly; raw models need them stated
- Pre-loaded HOT tier file contents directly in prompt (harness agents can `cat` them; raw models may not explore independently)
- Added "EDIT-TEST LOOP" guidance — harness agents do this natively; raw models need the pattern spelled out
- Changed "grep/find" references to explicit `exec("grep ...")` syntax

### 6.2 Review Prompt

```
You are an independent code reviewer. You have NOT seen the builder's work process.

Read the spec at {spec_path} — the ENTIRE file. Generate YOUR OWN checklist of
success criteria. Do not use anyone else's checklist.

Review: {git_diff}
Test results: {test_output}
Contract validation: {contract_validation_report}

For each criterion from YOUR checklist:
1. Is it implemented? Cite file:line.
2. Is it tested? Cite test name.
3. Could it fail in production? How?

MANDATORY ADVERSARIAL CHECKS:
A. One likely escaped defect — a bug tests won't catch but production will hit.
B. One untested path — a code path with no test coverage.
C. One test-vs-production gap — why tests might pass but production might fail.

{if is_bug_fix}
BUG FIX VERIFICATION:
- Reproduce test proving bug existed? Fails old, passes new? Deterministic?
- Evidence of investigation (instrumentation, data flow tracing)?
- Missing any → verdict FAIL.
{endif}

DETERMINISTIC AUDIT:
□ Public API changed → docs updated?  □ New deps → justified?
□ Migration → script?  □ Rollback path?  □ Logging for new features?
□ Test count ≥ baseline?  □ Files ≤5?  □ No secrets in diff?

OUTPUT JSON:
{
  "verdict": "PASS|FAIL|NEEDS_INFO",
  "criteria_checked": [{"criterion":"...", "status":"met|unmet|partial", "evidence":"file:line"}],
  "escaped_defect": "...",
  "untested_path": "...",
  "test_vs_production_gap": "...",
  "blocking_issues": [...],
  "non_blocking_issues": [...],
  "confidence": 0.0-1.0
}

Zero findings is suspicious. Explain why — cite tests.
```

### 6.3 Security Review Prompt (Tier 2+)

```
You are an adversarial security reviewer. Your job is to BREAK this code.

FRAMEWORK: OWASP Top 10 (2021) + STRIDE threat modeling.

Diff: {git_diff}

STRIDE ANALYSIS:
- Spoofing: impersonation of user/service/component?
- Tampering: data modified without detection?
- Repudiation: actions without adequate audit trail?
- Information Disclosure: sensitive data leaks?
- Denial of Service: availability degradation?
- Elevation of Privilege: unauthorized access escalation?

OWASP TOP 10:
A01. Broken Access Control    A02. Cryptographic Failures
A03. Injection                A04. Insecure Design
A05. Security Misconfiguration A06. Vulnerable Components
A07. Auth Failures            A08. Data Integrity Failures
A09. Logging Failures         A10. SSRF

ADDITIONAL: Race conditions, input validation gaps, resource exhaustion.

For each finding: STRIDE + OWASP category, severity (LOW/MEDIUM/HIGH/CRITICAL),
file:line, proof of concept, recommended fix.

Blocking threshold: any HIGH or CRITICAL blocks the build.

Output JSON: {"findings": [...], "blocking": true|false, "summary": "..."}
```

### 6.4 Escalation Template

Include: feature name, task ID, failure class, iterations used/max, circuit breaker signal, chronological summary, root cause, approaches tried, rejection ledger summary, 2-3 options with tradeoffs, recommendation, specific ask.

---

## 7. Failure Taxonomy + Escalation

**Critical budget rule:** Only `spec_ambiguity` and `model_limitation` consume retry budget. Environment failures are NOT the agent's fault.

| Failure Class | Detection | Action | Budget? |
|---|---|---|---|
| **spec_ambiguity** | Builder/reviewer disagree on intent; unmeasurable criteria | Ask Karan with A/B/C options. Don't resume until clarified. | Yes |
| **env_failure** | Deps won't install, service unreachable, wrong runtime | Fix environment. Re-run preflight. Resume where left off. | **No** |
| **missing_dep** | Needs API key, SDK, fixture data | Document exactly what's needed. Karan provides. Resume. | **No** |
| **arch_mismatch** | Task requires structural changes codebase can't support | Propose architecture change with effort estimate. | Yes |
| **model_limitation** | Same wrong pattern 3+ times | Try different model. If still failing, flag for human-assist. | Yes |

Each class determines the escalation message format.

---

## 8. Memory System

### Architecture

```
SOUL.md + IDENTITY.md           → Core persona (always loaded)
USER.md                          → User context (always loaded)
MEMORY.md                        → Curated long-term memory (main session only)
memory/YYYY-MM-DD.md             → Raw daily logs
knowledge/projects/*.md          → Per-project context (Obsidian wikilinks)
Session transcripts              → QMD-indexed (BM25 + vector + reranking)
memory/lessons.jsonl             → Machine-queryable build lessons
memory/build-costs.jsonl         → Cost tracking per build
tools/build-loop/states/         → Persisted build states
```

### Tiered Context Management

| Tier | What | When Loaded |
|---|---|---|
| **HOT** | Current task files, active spec section, rejection ledger | Always — injected into every agent prompt |
| **WARM** | Related files, project knowledge, recent lessons | On-demand when agent needs broader context |
| **COLD** | Full project history, all transcripts, archived specs | Searchable via QMD/grep — never bulk-loaded |

### Lessons JSONL

Schema: `{"id","ts","category","tags":[],"lesson","severity","project"}`

At task start, filter by project + tags, inject top-5 most critical as "Constraints from prior builds."

**Seeded lessons (from real failures):**

```jsonl
{"id":"lsn-001","ts":"2026-03-12","category":"testing","tags":["mocks","api"],"lesson":"Mocks encoding API assumptions will pass even when the real API signature is different. Always verify against real SDK types.","severity":"critical","project":"credential-vault"}
{"id":"lsn-002","ts":"2026-03-12","category":"debugging","tags":["plugin","restart"],"lesson":"SIGUSR1 does not reload compiled plugin code. Full restart + rebuild required.","severity":"high","project":"credential-vault"}
{"id":"lsn-003","ts":"2026-03-04","category":"config","tags":["gateway","crash"],"lesson":"Invalid config keys crash gateway on startup. Always validate against live schema.","severity":"critical","project":"openclaw"}
{"id":"lsn-004","ts":"2026-03-18","category":"process","tags":["monitoring","ci"],"lesson":"Monitoring without action is useless. If CI fails, diagnose and fix immediately.","severity":"high","project":"openclaw-contributor"}
{"id":"lsn-005","ts":"2026-03-15","category":"process","tags":["sub-agents","specs"],"lesson":"Never paraphrase specs to sub-agents. Point them at the source file.","severity":"critical","project":"all"}
{"id":"lsn-008","ts":"2026-03-21","category":"architecture","tags":["orchestration","state"],"lesson":"Deterministic orchestration must be real code. LLMs make inconsistent re-run decisions.","severity":"critical","project":"all"}
{"id":"lsn-009","ts":"2026-03-21","category":"testing","tags":["reproduce","bugfix"],"lesson":"Every bug fix must start with a failing reproduce test.","severity":"critical","project":"all"}
{"id":"lsn-010","ts":"2026-03-12","category":"debugging","tags":["trace","verify"],"lesson":"Before debugging behavior, prove the new code is executing. Add a trace log.","severity":"critical","project":"all"}
{"id":"lsn-011","ts":"2026-03-16","category":"process","tags":["cleanup","subprocess"],"lesson":"Scripts that spawn subprocesses must handle cleanup on all exit paths.","severity":"high","project":"all"}
{"id":"lsn-013","ts":"2026-03-23","category":"security","tags":["crypto","hostname"],"lesson":"Never use unpinned hostname as cryptographic key derivation material.","severity":"critical","project":"credential-vault"}
```

### QMD Integration

QMD indexes session transcripts with hybrid search (BM25 + vector + reranking). Cold boot first query: 10-30s — set `timeoutMs: 30000`. Session transcript indexing jumped memory hit rate from 25% to 75%.

---

## 9. Dispatch

### Without a Coding Harness: What Changes

A coding harness (Claude Code, Codex) provides:
1. **Autonomous shell access** — the agent runs commands independently
2. **Iterative edit-test loops** — the agent edits code, runs tests, fixes, repeats
3. **File exploration** — `find`, `grep`, `cat` without asking
4. **Background process management** — long-running processes, monitoring

Without a harness, the **orchestrator must compensate**:
1. **MillieClaw runs commands explicitly** via `exec` tool and feeds results to the sub-agent
2. **The edit-test loop becomes orchestrator-mediated** — MillieClaw reads test output and decides whether to re-prompt
3. **File exploration is pre-loaded** — relevant files injected into the task prompt (HOT/WARM tiers matter more)
4. **Background work** — MillieClaw uses `exec background:true` + `process` tool

### Dispatch Patterns

#### Pattern A: MillieClaw Inline (Small Tasks)

For S-sized tasks (1 file, clear scope), MillieClaw executes directly:

```
1. Read relevant files (read tool)
2. Write/edit code (write/edit tools)
3. Run tests (exec tool)
4. Fix if needed (edit tool + re-run)
```

No sub-agent overhead. Fastest path. Use for Tier 0-1 tasks.

#### Pattern B: Sub-Agent Spawn (Medium/Large Tasks)

For M/L tasks, spawn an isolated sub-agent session:

```json
{
  "task": "[Full task prompt from §6.1, including spec path and context files]",
  "runtime": "subagent",
  "model": "anthropic/claude-opus-4-6",
  "mode": "run",
  "runTimeoutSeconds": 1800
}
```

The sub-agent has the same tool access (read/write/exec) and works autonomously within its session. MillieClaw monitors via `subagents list` and reads output when complete.

**Critical difference:** Without a harness, the sub-agent's tool calls ARE the edit-test loop. Each tool call is visible to OpenClaw. This gives MORE observability than a coding harness (where the agent runs opaquely).

#### Pattern C: Cross-Model Review

```
1. Model A implements (sub-agent spawn with model X)
2. Deterministic gates (tests, lint, types) — run by MillieClaw via exec
3. Model B reviews (sub-agent spawn with different model)
4. Issues → back to Model A (or MillieClaw fixes inline if small)
```

Models available: Opus 4.6, GPT-5.4 (Codex alias), Sonnet, MiniMax, Gemini — any model OpenClaw can route to.

#### Pattern D: Parallel Execution

Max 3 concurrent sub-agents. Each gets own worktree:

```bash
git worktree add -b task/component-a /tmp/component-a main
git worktree add -b task/component-b /tmp/component-b main
```

Spawn sub-agents with `cwd` set to each worktree. Merge least-dependent first. Full test suite after merge.

### What We Gain Without a Harness

1. **Full observability** — every tool call is logged; no opaque agent internals
2. **Model flexibility** — swap models per-task without CLI compatibility concerns
3. **No CLI dependencies** — no `claude` binary, no `codex` binary, no version pinning
4. **Simpler error handling** — tool call failures are structured, not stderr parsing
5. **Cost transparency** — token usage broken down per tool call, not aggregated by an opaque harness

### What We Lose Without a Harness

1. **Autonomous iteration speed** — the agent can't self-loop on edit→test→fix without orchestrator mediation (unless the sub-agent session is long enough to do this independently)
2. **Built-in file exploration** — Claude Code's `find`/`grep` integration is smoother than injecting context
3. **Session-level caching** — coding harnesses maintain internal state between edits; sub-agents start fresh per spawn
4. **Native worktree support** — Claude Code's `--worktree` flag vs. manual `git worktree` setup

**Net assessment:** For most governance-layer concerns (state machine, failure taxonomy, review protocol, contract validation), **nothing changes**. The 10% that changes is all in dispatch mechanics and context loading. The harness capabilities that matter most (iterative edit-test loops) can be replicated by spawning sub-agents with sufficient autonomy and timeout.

---

## 10. Cost Framework

### Per-Feature Budgets

| Size | Tasks | Token Budget | Cost Budget |
|---|---|---|---|
| Small (Tier 0-1) | 1-2 | 500K | $5 |
| Medium (Tier 1-2) | 3-5 | 2M | $25 |
| Large (Tier 2-3) | 6+ | 5M | $75 |

**Warnings:** 70% → consider simplifying. 90% → finish current or abort. 100% → state machine blocks new spawns.

### Model Routing

Any model accessible through OpenClaw can fill any role. Recommended routing:

| Pass | Tier 0-1 | Tier 2-3 |
|---|---|---|
| Build (Pass 1) | Cost-efficient (Sonnet, Haiku, Mini) | Strongest available (Opus, GPT-5.4) |
| Contract (Pass 2) | Deterministic (no model) | Deterministic (no model) |
| Review (Pass 3) | Cost-efficient (different model than builder) | Strongest available (different model than builder) |
| Security | Skip | Strongest available |

**The "different model" rule matters more here.** Without a harness providing its own internal review, the cross-model review in Pass 3 is the primary defense against model-specific blind spots. If builder used Opus → reviewer should use GPT-5.4 or vice versa.

### Waste Reduction

- Small fix → incremental review (changed portion only)
- Spec in prompt → section reference, not full re-read
- Tier 0-1 → skip security reviews
- Diff > 500 lines → split review by file group

### Cost Logging

Append to `memory/build-costs.jsonl`: `{"build_id","feature","tasks","total_tokens","cost_usd","iterations","wall_clock_min","outcome","model_breakdown"}`

---

## 11. Risk Tiers

| Tier | Scope | Build Passes | Human Gates |
|---|---|---|---|
| 0 | Docs, comments, config values | Pass 1 + Pass 2 (L1) | None |
| 1 | Small code (<100 lines, 1-2 files) | Pass 1 + Pass 2 + Pass 3 (spec) | None |
| 2 | Core logic, multiple files, new features | All passes + security review | None |
| 3 | Security, auth, credentials, infra | All passes + Karan checkpoint | Karan reviews |

**Deterministic assignment:**
```python
def assign_tier(changed_files, lines_changed, keywords):
    security_kw = {"auth", "credential", "secret", "permission", "token", "password", "encrypt", "key", "cert"}
    if any(kw in " ".join(changed_files + keywords).lower() for kw in security_kw):
        return 3
    if lines_changed > 200 or len(changed_files) > 3:
        return 2
    if any(f.endswith(('.py', '.ts', '.js', '.rs', '.go')) for f in changed_files):
        return 1
    return 0
```

---

## 12. Parallelism Policy

**Not the default.** Parallel OK only when: no shared files, each task has own test command, clean merge expected, rate limit headroom. **Max 3 concurrent agents.** Each gets own worktree. Merge least-dependent first. Full test suite after merge.

Serialize: tightly coupled logic, shared files, weak test coverage.

---

## 13. What We Build vs. What Exists

### Already Exists (Use It)

| Capability | Provided By |
|---|---|
| Sub-agent spawning | `sessions_spawn` (runtime: "subagent") |
| Model routing | OpenClaw model config (aliases: codex, opus, etc.) |
| Parallel isolation | `git worktree` + multiple sub-agent spawns |
| Session monitoring | `subagents list`, `process` tool |
| Direct tool access | read/write/edit/exec/browser/web_search |
| Memory search | QMD (BM25 + vector + reranking) |
| Project context | Obsidian knowledge base |

### What We Build (Our Value)

| What | Priority |
|---|---|
| `tools/build-loop/build_loop.py` — state machine | **Critical** |
| `tools/build-loop/test_build_loop.py` — tests | **Critical** |
| `tools/build-loop/preflight.sh` — preflight | High |
| `docs/templates/` — prompt templates | High |
| `memory/lessons.jsonl` — seeded lessons | High |
| Context loader for sub-agents (HOT/WARM file injection) | **High** (compensates for no harness) |

---

## 14. Artifact Chain Reference

| Phase | Consumes | Produces |
|---|---|---|
| **Preflight** (§4.1) | Repo state, env vars | `preflight.json` |
| **Ambiguity Detection** (§4.2) | `preflight.json`, draft spec | Resolved spec or questions |
| **Spec** (§4.3) | Validated scope | Spec file (`docs/<feature>-spec.md`) |
| **Decomposition** (§4.4) | Approved spec | Task list in `states/<id>.json` |
| **Pass 1: Build** (§4.5) | Task prompt + spec + rejections | Code changes + test output |
| **Pass 2: Contract** (§4.8) | Code changes | Contract validation report |
| **Pass 3: Review** (§4.9) | Spec + diff + tests + contract report | Review verdict + audit report |
| **Integration** (§4.5) | All task branches | Merged branch |
| **Ship** (§4.14) | Merged branch + spec | PR or published package |
| **Learn** (§4.15) | Completed build | `lessons.jsonl` + knowledge + cost log |

**Rule:** Each phase reads the file produced by the previous phase. Never a summary, never from memory.

---

## 15. Unique Differentiators

Based on competitive analysis of Devin, OpenHands/CodeAct, SWE-agent, Aider, Cursor Agent, Open SWE, Harness AI, Factory, and Sweep AI (March 2026):

### What No Competitor Has

1. **Failure Taxonomy with Differential Response (§7)**
   No competitor classifies build failures into distinct categories (spec ambiguity, environment, missing deps, architecture mismatch, model limitation) with different remediation paths. Others retry uniformly or just stop. This system routes `env_failure` to environment fixes (no budget penalty) while routing `spec_ambiguity` to human clarification — fundamentally different actions for fundamentally different problems.

2. **Anti-Rubber-Stamp Review Protocol (§4.9)**
   Devin, OpenHands, and Aider all have some form of self-review, but none enforce: (a) separate agent spawn with zero shared context, (b) mandatory adversarial findings (escaped defect, untested path), (c) cross-engine review (different model = different biases). Most systems have the builder review its own work, which is inherently conflicted.

3. **Graded Contract Validation (§4.8)**
   Five levels from type-checking to staging smoke tests, all deterministic (no LLM), declared per-project. No competitor has a formalized, escalating contract validation ladder. Most rely on "run tests" as the only validation — this system validates against real SDK types, golden fixtures, and integration harnesses before any reviewer sees the code.

4. **Circuit Breaker with Three Independent Signals (§4.10)**
   Competitors use naive retry counting ("attempt 3/5"). This system tracks no-progress, same-error, and output-decline independently — catching different failure modes (stuck loops, repeated errors, model degradation) that simple counters miss.

5. **Rejection Ledger (§4.11)**
   Persistent record of failed approaches injected into retry prompts. No competitor prevents agents from re-attempting the same failed fix. This eliminates the "rediscover the same dead end" pattern that wastes 2-3 iterations per stuck task.

6. **Investigation-First Bug Fix Protocol (§4.6)**
   Beyond "write a test first" — mandates tracing actual data flow with instrumentation before forming a hypothesis. The three-strike rule (3 failed fixes = wrong mental model → re-investigate) is unique. Competitors treat bug fixes as "try a fix, run tests, retry."

7. **Deterministic State Machine as Orchestrator (§5)**
   OpenHands uses event-stream architecture and Open SWE uses Deep Agents' planning, but both rely on LLM-interpreted orchestration. This system's state machine is pure Python — same input always produces same transition, survives session death, and never drifts. The LLM (MillieClaw) makes strategy decisions; the state machine enforces them deterministically.

8. **Tiered Context Management (§8)**
   HOT/WARM/COLD context tiers prevent the "load everything" anti-pattern that causes context overflow in long builds. Most competitors either dump full context or have no formal context management strategy.

9. **Cross-Project Memory with Lesson Injection (§8)**
   Machine-queryable `lessons.jsonl` with per-project filtering and severity-ranked injection into build prompts. Competitors have session memory at best — none systematically learn from past builds across projects and inject those lessons into future builds.

10. **Truly Engine-Agnostic — No Harness Required**
    Unlike Devin (proprietary, single-engine) or OpenHands (primarily CodeAct), this system doesn't even require a coding harness. Any model with basic tool access (read/write/exec) can serve as the execution engine. The governance layer wraps raw models just as effectively as it wraps Claude Code or Codex — because the value is in orchestration, not in the engine's shell integration. v4.6.2 proves this: ~90% of the spec is identical whether the executor is a $500/mo coding agent or a bare API call.

### What Competitors Do Better

- **Devin:** Cloud sandboxing, always-available web environment, Devin Wiki for codebase documentation
- **OpenHands:** Open-source community (186+ contributors), formal SDK with MCP integration, containerized environments
- **Cursor:** Real-time IDE integration, developer-in-the-loop for immediate feedback
- **Aider:** Simplicity — single CLI tool that just works for interactive coding

---

## 16. Quick Reference Card

```
BEFORE BUILD: CODING-BEST-PRACTICES.md → project knowledge → preflight.sh →
  ambiguity check → decompose (≤5 files, verification triple) → start_build()

PER TASK:
  Pass 1 BUILD: sub-agent spawn (or inline) → tests + lint green? (bug fix → investigate→reproduce→fix→verify)
  Pass 2 CONTRACT: strongest validation level (deterministic, no LLM)
  Pass 3 VALIDATE: reviewer (different model) + audit + mutation test (+ security Tier 2+) (+ browser QA if UI)

CIRCUIT BREAKER: no-progress(2) OR same-error(3) OR output-decline(70%) → HALT

FAILURES: spec_ambiguity→ask | env→fix | missing_dep→document | arch→propose | model→switch

BUG FIX: investigate→locate→reproduce→patch→validate (3 strikes → re-investigate)

SHIP: sync main → full suite → lint → coverage → secrets → spec criteria → docs → commits → PR → CI

COST: S=500K/$5 | M=2M/$25 | L=5M/$75 | warn@70% decide@90% abort@100%

DISPATCH: sessions_spawn(task, runtime:"subagent", model:"<any>") OR inline (read/write/exec)

ARTIFACTS: preflight.json → spec.md → states/<id>.json → code+tests → contract report → review → PR → lessons.jsonl

ENGINE-AGNOSTIC: Governance layer (state machine, failure taxonomy, rejection ledger,
  circuit breakers, contract validation, review protocol) is 100% engine-independent.
  Only dispatch + context loading changes between harness and raw model execution.
```

---

## 17. Future Work

- **Property-based testing synthesis** — algebraic properties and metamorphic relations instead of example-based tests
- **Self-play/debate for code review** — evidence-constrained debate bound to artifacts
- **Parallel candidate rollouts** — diverse patch attempts in parallel for high-stakes tasks
- **Supervisor runtime** — meta-agent watching for looping trajectories and schema drift
- **Model-specific harness tuning** — per-model policy bundles instead of universal prompts
- **Claude Code Agent Teams** — up to 10 parallel teammates with shared task lists

---

## 18. v4.6.2 Delta Summary: What Actually Changes Without a Coding Harness

### What Changes (the ~10%)

| Aspect | With Harness (v4.6.1) | Without Harness (v4.6.2) | Impact |
|---|---|---|---|
| **Dispatch** | `claude --print --bypassPermissions` or ACP spawn | `sessions_spawn` with any model, or inline tool calls | Simpler — no CLI dependencies |
| **Context loading** | Agent explores files autonomously (`cat`, `find`, `grep`) | HOT tier pre-loaded in prompt; WARM referenced explicitly | More orchestrator work upfront; better control |
| **Edit-test loop** | Agent loops internally (opaque) | Orchestrator mediates OR sub-agent with sufficient timeout self-loops via tools | More observable; slightly slower |
| **File exploration** | Native to harness (find/grep/cat) | Via `exec("grep ...")` and `read` tool calls | Functionally equivalent; more verbose |
| **Parallel execution** | `claude --worktree` flag | Manual `git worktree` + multiple `sessions_spawn` | Same result; more setup |
| **Token visibility** | Aggregated by harness (internal sub-agents hidden) | Full breakdown per tool call | **Better** — more transparent |
| **Error handling** | Parse stderr from CLI | Structured tool call failures | **Better** — more reliable |
| **Model lock-in** | Tied to Claude Code or Codex CLI | Any model OpenClaw can route to | **Better** — true flexibility |

### What Doesn't Change (the ~90%)

- State machine (§5) — 100% engine-agnostic
- Failure taxonomy (§7) — 100% engine-agnostic
- Circuit breakers (§4.10) — 100% engine-agnostic
- Rejection ledger (§4.11) — 100% engine-agnostic
- Contract validation (§4.8) — was already deterministic (no LLM)
- Review protocol (§4.9) — context isolation, mandatory findings, cross-model review all unchanged
- Bug fix protocol (§4.6) — investigate→reproduce→fix→verify works regardless of executor
- Spec workflow (§4.1-4.4) — all pre-build phases are orchestrator-level
- Ship checklist (§4.14) — all shell commands, engine-irrelevant
- Memory system (§8) — fully orchestrator-owned
- Cost framework (§10) — budgets, warnings, tracking all the same
- Risk tiers (§11) — deterministic assignment from file/line analysis
- Prompt templates (§6) — minor wording changes but same structure

### The Key Insight

**The governance layer IS the product.** Coding harnesses are just one possible execution backend. The state machine doesn't care if the code was written by Claude Code with shell access, by GPT-5.4 via tool calls, or by a human with vim. It tracks the same state, enforces the same gates, and produces the same artifacts.

This means:
1. **The architecture survives model commoditization.** When the next model drops, swap it in. Nothing else changes.
2. **The architecture survives harness obsolescence.** If Claude Code or Codex disappear tomorrow, the governance layer keeps working with raw models.
3. **The architecture scales DOWN.** A weaker model with strong governance outperforms a stronger model with no governance (the 45-57% SWE-bench variance proves this).
4. **The real competitive moat is the orchestration intelligence** — failure classification, rejection memory, contract validation ladders, anti-rubber-stamp reviews. None of these depend on which model writes the code.

---

*The architecture: MillieClaw keeps the judgment; deterministic code keeps the books; the investigate→reproduce→fix→verify cycle keeps us honest. The execution engine is a replaceable part. The governance layer is not.*
