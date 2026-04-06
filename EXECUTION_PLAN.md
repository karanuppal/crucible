# Agentic Harness v5.2 — Execution Plan

**Status:** In Progress  
**Date:** 2026-04-06  
**Ground Truth:** PRD v5.2 + Technical Design v5.2  
**Repository:** `~/Projects/agentic-harness-v5.2/`

---

## Overview

This execution plan breaks down the Agentic Harness v5.2 implementation into 6 phases with clear validation criteria, testing strategies, and reviewer agent requirements for each phase.

**Key Principles:**
- Each phase must be validated before moving to the next
- Reviewer agents are independent and context-isolated from builder agents
- Validation is evidence-backed, not self-certified
- All code lives in the git repository

---

## Phase 1: Deterministic Substrate

### Duration
**Estimated:** 2-3 days  
**Goal:** Establish the core state contracts and ledger system

### Deliverables

#### 1.1 State Contracts
- `ProjectState` — tracks long-lived project continuity
- `BuildState` — tracks one implementation campaign
- `TaskState` — tracks a decomposed unit of work
- `RunState` — tracks an individual worker run
- `ValidationState` — tracks validation evidence
- `IntegrationState` — tracks merge/fan-in work

#### 1.2 Append-Only Ledger
- Event schema with types: `spec.created`, `task.created`, `run.spawned`, `run.progress`, `run.timed_out`, `validation.completed`, etc.
- Artifact reference system (spec, diff, test-output, build-log, screenshot, sample-output, review-report)

#### 1.3 Ambiguity Gate
- Output format: CLEAR, CLARIFY, SPLIT, DEFER
- Analysis categories: undefined terms, missing criteria, unclear scope, hidden dependencies, contradictions

#### 1.4 Failure Taxonomy
- `ambiguity_block` — ask user targeted question
- `environment_block` — fix environment, rerun
- `missing_dependency` — request/provide dependency
- `architecture_mismatch` — propose revision
- `model_limitation` — switch role/model/backend
- `validation_failure` — repair based on evidence
- `integration_conflict` — route to integrator
- `loop_detected` — trip circuit breaker

### Validation Criteria for Phase 1

| Criterion | How to Validate |
|-----------|-----------------|
| State contracts are serializable | JSON roundtrip test for all 6 state types |
| Ledger is append-only | Verify no update/delete operations, only append |
| Ambiguity gate produces valid output | Unit tests with sample inputs → expected outputs |
| Failure taxonomy covers all cases | Test each failure type triggers correct action |
| State persists across restarts | Write state → restart → read state → verify identical |

### Testing Strategy

- **Unit tests:** State serialization, ambiguity gate logic, failure classification
- **Integration tests:** Ledger append + read, state transitions
- **No sub-agents yet** — pure deterministic code validation

### Reviewer Agent for Phase 1

**Role:** Code Reviewer (context-isolated)  
**Focus:**
- State contract completeness — all required fields present?
- Ledger event schema correctness
- Ambiguity gate coverage
- Failure taxonomy exhaustiveness

**Review Criteria:**
- [ ] All 6 state types implemented with required fields
- [ ] Ledger append-only semantics enforced
- [ ] Ambiguity gate handles at least 5 ambiguity categories
- [ ] Each failure type has defined next action
- [ ] No state mutation outside of defined transitions

---

## Phase 2: Sub-Agent Management Cluster

### Duration
**Estimated:** 3-4 days  
**Goal:** Build the run graph, spawn/monitor/steer/kill/cleanup operations

### Deliverables

#### 2.1 Run Graph Model
- Parent/child run relationships
- Blocking vs non-blocking children
- Detachment and reattachment semantics
- Cancellation propagation rules
- `partial` as first-class run outcome

#### 2.2 Role Templates
- **builder** — implements changes
- **reviewer** — checks against spec + evidence
- **debugger** — investigates failing behavior
- **researcher/scout** — explores codebase or external docs
- **integrator** — merges parallel outputs and resolves collisions
- **salvage worker** — resumes or completes partial work after timeout/failure

#### 2.3 Spawn Policy
- When to spawn (multi-file, independent perspective, parallel work, long tasks)
- When to stay inline (tiny deterministic actions, state bookkeeping)

#### 2.4 Sub-Agent Controller
- `spawn(spec: RunSpec)` → RunHandle
- `send(runId, message)`
- `poll(runId)` → RunStatus
- `collect(runId)` → RunArtifacts
- `kill(runId)`
- Timeout detection and salvage triggers

#### 2.5 Active-Run Visibility
- Queryable view of: active runs, role, task association, last progress, status, blocked reason

#### 2.6 Rejection Ledger + Circuit Breaker
- Track attempted approaches, failure reasons, evidence
- Trip conditions: repeated same-error, no-progress, obvious looping

### Validation Criteria for Phase 2

| Criterion | How to Validate |
|-----------|-----------------|
| Run graph correctly models parent/child | Spawn 3 child runs → verify parent tracks them |
| Cancellation propagates to blocking children | Kill parent → verify children killed |
| Partial success tracked in ledger | Timeout mid-run → verify partial recorded |
| Role templates produce correct behavior | Spawn each role → verify role-specific actions |
| Spawn policy makes sensible decisions | Test with task sizes S/M/L → verify spawn/inline |
| Active-run visibility accurate | Spawn 3 runs → query → verify all 3 present |
| Circuit breaker trips at threshold | Loop 5x same failure → verify breaker trips |

### Testing Strategy

- **Mock sub-agent environment** — don't actually spawn OpenClaw sub-agents
- **Simulated runs** — use test harness to simulate spawn/poll/kill
- **State verification** — all run state changes tracked in ledger

### Reviewer Agent for Phase 2

**Role:** Integration Reviewer (context-isolated from builder)  
**Focus:**
- Run graph semantics correctness
- Role separation enforcement
- Cancellation propagation logic
- Circuit breaker threshold and behavior

**Review Criteria:**
- [ ] Run graph correctly handles parent/child lifecycle
- [ ] Each role template has distinct behavior
- [ ] Cancellation propagates only to blocking children
- [ ] Salvage worker can resume partial work
- [ ] Circuit breaker prevents repeated failed attempts
- [ ] Active-run view reflects actual state

---

## Phase 3: Validation and Review Foundation

### Duration
**Estimated:** 2-3 days  
**Goal:** Build the validation ladder, verification triples, evidence mapping, and completion gates before workflow automation depends on them

### Deliverables

#### 3.1 Validation Ladder
1. Static checks (lint, type check)
2. Targeted tests
3. Local build/run checks
4. Proof/demo artifacts
5. CI validation

#### 3.2 Verification Triple
Per task: what to build, how to verify, what failure looks like

#### 3.3 Evidence Mapping
- Each validation result maps to specific spec criteria
- Evidence stored in ledger with artifact refs

#### 3.4 Reviewer Workflow
- Reviewer receives: spec, diff, validation outputs
- Reviewer produces: criterion-by-criterion compliance, escaped defect, untested path, verdict

#### 3.5 Completion Semantics
- Must-pass vs informational gate distinction
- Task-complete conditions
- Build-complete conditions
- Anti-vacuity rule: evidence insufficient if it would pass after removing implementation

### Validation Criteria for Phase 3

| Criterion | How to Validate |
|-----------|-----------------|
| Validation ladder executes in order | Run full ladder → verify each level runs |
| Verification triple produces valid output | Test with sample task → verify triple complete |
| Evidence maps to criteria | Run validation → verify each criterion has evidence |
| Reviewer produces structured output | Spawn reviewer → verify output format |
| Must-pass gates block completion | Fail must-pass → verify build incomplete |
| Anti-vacuity rule enforced | Remove implementation → verify validation fails |

### Testing Strategy

- **Test validation ladder** with sample projects
- **Simulate validation failures** and verify gate behavior
- **Run reviewer** on sample diffs and verify output structure

### Reviewer Agent for Phase 3

**Role:** Validation Reviewer (strict, context-isolated)  
**Focus:**
- Validation ladder completeness
- Evidence quality
- Anti-vacuity enforcement
- Completion gate correctness

**Review Criteria:**
- [ ] All 5 validation ladder levels are executable
- [ ] Verification triples are complete (build/verify/failure)
- [ ] Evidence is tied to specific criteria
- [ ] Must-pass gates actually block completion
- [ ] Anti-vacuity rule catches fake validation

---

## Phase 4: Scheduling and Memory Foundation

### Duration
**Estimated:** 2-3 days  
**Goal:** Build machine-aware scheduling and harness-owned memory before scaling workflow automation

### Deliverables

#### 4.1 Machine Profile
- CPU cores, RAM, swap, free disk, GPU availability

#### 4.2 Task Intensity Classification
- **light** — review, research, docs, simple edits
- **medium** — moderate coding, normal tests
- **heavy** — large builds, heavy test suites, parallel integration

#### 4.3 Adaptive Concurrency Heuristics
- Preserve CPU headroom
- Preserve memory headroom
- Reduce concurrency for heavy tasks
- Allow higher parallelism for light work
- Prefer isolated worktrees for parallel builders

#### 4.4 Harness Memory Retrieval/Injection
- Store/retrieve project-specific context
- Inject harness memory into sub-agent sessions
- Distinguish from host conversational memory

#### 4.5 Project Lessons Persistence
- Lessons from failures stored in ledger
- Rejection ledger consulted before retry
- Lessons survive across builds

### Validation Criteria for Phase 4

| Criterion | How to Validate |
|-----------|-----------------|
| Machine profile accurate | Compare against system utilities |
| Intensity classification correct | Classify sample tasks → verify reasonable |
| Scheduler respects limits | Run heavy task → verify CPU/memory preserved |
| Lessons persist across runs | Complete build → start new → verify lessons available |
| Memory injection works | Inject memory → spawn sub-agent → verify context present |

### Testing Strategy

- **Profile validation** against system utilities (sysctl, vm_stat, etc.)
- **Scheduler stress test** — run multiple tasks, verify limits respected
- **Memory persistence test** — write lessons → restart → read lessons

### Reviewer Agent for Phase 4

**Role:** Performance Reviewer (context-isolated)  
**Focus:**
- Machine profile accuracy
- Scheduler behavior under load
- Memory persistence correctness

**Review Criteria:**
- [ ] Machine profile matches actual hardware
- [ ] Scheduler prevents resource thrashing
- [ ] Lessons persist correctly
- [ ] Harness memory is isolated from host memory

---

## Phase 5: Unified Project Workflows

### Duration
**Estimated:** 3-4 days  
**Goal:** Existing project intake + greenfield bootstrap → first working version, now built on top of validation and scheduling foundations

### Deliverables

#### 5.1 Existing-Project Intake
- Repository inspection (language, framework, test setup)
- Branch/worktree isolation for parallel work
- Task graph from existing code state

#### 5.2 Greenfield Bootstrap
- Baseline stack selection (web app, CLI, library, API service)
- Project scaffold generation
- Local repo creation
- Remote GitHub repo creation (if credentials available)
- CI baseline (at least one CI job covering install + test/build)
- First-working-version gate

#### 5.3 Greenfield Defaults Matrix
| Project Type | Default Stack |
|--------------|---------------|
| Web app | Python backend + React frontend, uv for Python env/package management, pytest + Vitest |
| CLI | Python + Typer, uv, pytest |
| Python library | Python + uv + pytest |
| API service | FastAPI + uvicorn + uv + pytest |

#### 5.4 First-Working-Version Criteria
- Repo exists locally
- Remote repo exists (when credentials available)
- Project scaffold is coherent
- Local run/build succeeds
- Minimal CI baseline configured
- At least one proof artifact exists

### Validation Criteria for Phase 5

| Criterion | How to Validate |
|-----------|-----------------|
| Existing project inspection produces accurate data | Test against 3 real repos → verify language/framework detection |
| Worktree isolation works | Create worktree → verify isolation from main branch |
| Greenfield produces valid scaffold | Bootstrap 3 project types → verify each runs |
| Remote repo creation works | Create repo → verify exists on GitHub |
| CI baseline is functional | Push to remote → verify CI runs and passes |
| First-working-version gate passes | Complete bootstrap → verify all criteria met |

### Testing Strategy

- **Test repositories:** Create temp repos for testing intake
- **Greenfield testing:** Bootstrap real projects, verify they build
- **CI validation:** Real GitHub Actions runs

### Reviewer Agent for Phase 5

**Role:** End-to-End Reviewer (context-isolated)  
**Focus:**
- Project intake accuracy
- Greenfield scaffold quality
- First-working-version completeness
- Worktree isolation correctness
- Python/uv default consistency

**Review Criteria:**
- [ ] Inspection detects language, framework, test setup correctly
- [ ] Worktrees are properly isolated from main branch
- [ ] Greenfield scaffolds are runnable and coherent
- [ ] Python is the default backend choice unless spec requires otherwise
- [ ] uv is the default Python package/project manager unless spec requires otherwise
- [ ] GitHub repo creation works (or gracefully degrades)
- [ ] CI baseline runs and passes
- [ ] First-working-version criteria are all met

---

## Phase 6: Optional Accelerators

### Duration
**Estimated:** 2-3 days (optional, lower priority)  
**Goal:** Backend abstraction for Claude Code, Codex integration

### Deliverables

#### 6.1 Execution Backend Interface

```ts
interface ExecutionBackend {
  name: string;
  supportsPersistentSession: boolean;
  supportsNativeWorktrees: boolean;
  supportsBackgroundLoops: boolean;
  supportsDirectFileOps: boolean;

  spawn(spec: RunSpec): Promise<RunHandle>;
  send(runId: string, message: string): Promise<void>;
  poll(runId: string): Promise<RunStatus>;
  collect(runId: string): Promise<RunArtifacts>;
  kill(runId: string): Promise<void>;
}
```

#### 6.2 Initial Backends
- OpenClaw sub-agent backend (already exists)
- Inline deterministic backend (tiny actions)
- Future: Claude Code backend
- Future: Codex backend

#### 6.3 Backend Capability Routing
- Route to appropriate backend based on task requirements
- Fallback chain when preferred backend unavailable

### Validation Criteria for Phase 6

| Criterion | How to Validate |
|-----------|-----------------|
| Backend interface is sufficient | All required methods implemented |
| OpenClaw backend works | Spawn via OpenClaw → verify execution |
| Capability routing works | Request specific capability → verify routed correctly |
| Fallback works | Disable preferred backend → verify fallback used |

### Testing Strategy

- **Interface tests** — verify all methods present
- **Routing tests** — mock backends, verify routing logic
- **Fallback tests** — simulate backend failure, verify fallback

### Reviewer Agent for Phase 6

**Role:** Architecture Reviewer (context-isolated)  
**Focus:**
- Interface completeness
- Backend abstraction correctness
- Routing logic

**Review Criteria:**
- [ ] Backend interface covers all required capabilities
- [ ] OpenClaw backend is functional
- [ ] Routing selects appropriate backend
- [ ] Fallback chain works correctly

---

## Summary: Phase Timeline

| Phase | Duration | Key Deliverables | Blocker Check |
|-------|----------|------------------|---------------|
| Phase 1 | 2-3 days | State contracts, ledger, ambiguity gate, failure taxonomy | All 6 state types serializable, append-only ledger enforced |
| Phase 2 | 3-4 days | Run graph, role templates, spawn controller, circuit breaker | Runs spawn/poll/kill correctly, visibility works |
| Phase 3 | 2-3 days | Validation ladder, verification triples, evidence mapping, completion gates | Evidence maps to criteria, gates block completion |
| Phase 4 | 2-3 days | Machine profile, scheduler, harness memory, lessons | Scheduler respects limits, lessons persist |
| Phase 5 | 3-4 days | Project intake, greenfield bootstrap, first-working-version | Projects bootstrap successfully, CI passes |
| Phase 6 | 2-3 days | Backend interface, capability routing (optional) | Interface sufficient, routing works |

**Total Estimated Duration:** 14-20 days

---

## Repository Structure

```
agentic-harness-v5.2/
├── README.md
├── EXECUTION_PLAN.md          # This file
├── docs/
│   ├── PRD_v5.2.md           # Copied from workspace
│   └── TECHNICAL_DESIGN_v5.2.md
├── src/
│   ├── state/                # Phase 1: State contracts
│   │   ├── ProjectState.ts
│   │   ├── BuildState.ts
│   │   ├── TaskState.ts
│   │   ├── RunState.ts
│   │   ├── ValidationState.ts
│   │   └── IntegrationState.ts
│   ├── ledger/               # Phase 1: Ledger
│   │   ├── index.ts
│   │   └── events.ts
│   ├── ambiguity/            # Phase 1: Ambiguity gate
│   │   └── index.ts
│   ├── failures/             # Phase 1: Failure taxonomy
│   │   └── index.ts
│   ├── runner/               # Phase 2: Sub-agent management
│   │   ├── controller.ts
│   │   ├── roles/
│   │   └── scheduler.ts
│   ├── workflows/            # Phase 3: Project workflows
│   │   ├── intake/
│   │   └── bootstrap/
│   ├── validation/           # Phase 4: Validation
│   │   ├── ladder.ts
│   │   └── reviewer.ts
│   ├── memory/               # Phase 5: Harness memory
│   │   └── index.ts
│   └── backends/             # Phase 6: Backend interface
│       ├── interface.ts
│       └── openclaw.ts
└── tests/
    ├── state/
    ├── runner/
    ├── workflows/
    └── validation/
```

---

## Next Steps

1. **Approve this execution plan** — confirm phases, timeline, validation criteria
2. **Start Phase 1** — begin deterministic substrate implementation
3. **Spin up Reviewer Agent** — for Phase 1 code review

