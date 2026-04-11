# Crucible Specification v7.1

## Status

This document is the **single unified ground truth** for Crucible.

It replaces fragmented prior thinking and should be treated as the only normative specification for:
- product intent
- architecture
- control-plane vs execution-core boundaries
- LLM and prompt-management rules
- feature prioritization
- integration model and invocation surfaces

This spec is written to be understandable by a strong engineer reading cold.

---

## 1. Purpose

Crucible exists to close the gap between:
- a human saying what should be built or fixed
- an agent producing code
- a system being able to **reliably drive work to closure**

The key idea is not “have an LLM write code.”
The key idea is:

> Build a runtime that can take a task, execute it with evidence, validate it, repair it when needed, and report a structured outcome that a higher-level orchestrator can reason about.

Crucible should become the execution substrate for agentic software delivery where:
- tasks are explicit
- work is durable
- retries are typed
- evidence is first-class
- failure handling is not vibes-based
- chat/UI is an observer and control surface, not the execution brain itself

---

## 2. The core product problem

Most current agentic coding systems fail in one of two ways:

1. **Thin wrapper over a coding agent**
   - good at a single pass of code generation
   - weak at durable execution, verification, recovery, and state

2. **One giant orchestration loop**
   - planning, coding, retrying, judging, and completion logic all mixed together
   - difficult to reason about
   - hard to make deterministic
   - poor failure isolation

Crucible should solve the real problem:

> Separate global workflow orchestration from task-local execution so the system can both think clearly about work and execute that work reliably.

---

## 3. Design goals

### Primary goals

- Drive coding tasks to a **structured terminal outcome**:
  - passed
  - failed
  - blocked
  - escalated
- Make execution **durable and restart-safe**
- Make retries **policy-driven**, not free-form
- Treat evidence as a first-class output
- Allow higher-level systems to reason over results without re-parsing chat logs
- Keep the execution engine usable from:
  - CLI
  - OpenClaw tools
  - higher-level control planes
  - future UI surfaces

### Secondary goals

- Support multiple execution roles and models
- Support typed attempts such as build, repair, review, verify, integrate, revalidate
- Support human checkpoints when needed
- Support progressively stronger autonomy without rewriting the architecture

### Non-goals

Crucible is not:
- a chat product
- a pure planner with no runtime authority
- a monolithic “single agent loop” that owns every decision at every level
- a replacement for every coding agent; it is the structured runtime around them

---

## 4. Product principles

1. **Durability over cleverness**
   - A boring resumable system beats a magical but fragile one.

2. **Evidence over assertions**
   - “It should work” is not an outcome.
   - Logs, diffs, test output, validation reports, and attempt records are outcomes.

3. **Typed control flow over free-form retries**
   - The system should know whether it is building, repairing, reviewing, or revalidating.

4. **Separation of global vs local decision-making**
   - Task selection is different from task execution.
   - Workflow policy is different from code generation.

5. **Prompt policy should be explicit**
   - Prompt construction should be managed, versionable, and inspectable.

6. **The runtime should own closure semantics**
   - Chat should observe and steer.
   - Crucible should execute and classify.

---

## 5. Mental model

Crucible should be understood as two nested layers:

- **Control Plane** = outer workflow state machine
- **Execution Core** = inner task-execution state machine

The clean relationship is:

```text
SELECT TASK
  -> PREPARE TASK PACKET
  -> RUN EXECUTION CORE(task_packet)
  -> INGEST EXECUTION RESULT
  -> DECIDE NEXT ACTION
```

So the execution core is **not** a peer competing with the control plane.
It is a **subsystem invoked by it**.

The simplest useful phrasing is:

- The **control plane** decides what should happen next.
- The **execution core** tries to make one task actually succeed.

---

## 6. Architecture overview

## 6.1 Top-level architecture

```text
                           +----------------------+
                           |  Human / API / Chat  |
                           +----------+-----------+
                                      |
                                      v
                         +---------------------------+
                         |       CONTROL PLANE       |
                         |---------------------------|
                         | backlog intake            |
                         | prioritization            |
                         | dependency tracking       |
                         | policy selection          |
                         | retry / escalation rules  |
                         | prompt policy selection   |
                         | model routing             |
                         | budget / timeout control  |
                         | terminal classification   |
                         +------------+--------------+
                                      |
                              TaskPacket|
                                      v
                         +---------------------------+
                         |      EXECUTION CORE       |
                         |---------------------------|
                         | build execution context   |
                         | instantiate prompts       |
                         | run codegen / edits       |
                         | run tools / tests         |
                         | local diagnose / repair   |
                         | review / verify           |
                         | package evidence          |
                         +------------+--------------+
                                      |
                           ExecutionResult + Artifacts
                                      v
              +-------------------+   +----------------------+   +------------------+
              |   STATE STORE     |   |   ARTIFACT STORE     |   |  EVENT / STATUS  |
              | run manifests     |   | diffs                |   | timeline         |
              | attempts          |   | logs                 |   | UI/chat updates  |
              | adapter state     |   | test output          |   | operator actions |
              | policy snapshots  |   | review reports       |   |                  |
              +-------------------+   +----------------------+   +------------------+
```

---

## 6.2 Control Plane

The control plane owns **workflow-level state and decisions**.

### Responsibilities

- ingest goals, tasks, or plans
- normalize work into executable task packets
- manage backlog and dependency graph
- choose execution policy for each task
- choose prompt family / model routing / tool allowances
- set retry budgets and timeouts
- decide whether a result means:
  - complete
  - retry
  - split task
  - escalate
  - block
  - abandon
- coordinate multiple tasks across a larger workflow
- persist workflow-level progress

### Questions the control plane answers

- What task should run now?
- Under what policy and budget should it run?
- Is the task blocked by another task?
- If execution fails, should we retry, split, escalate, or stop?
- Is the overall workflow complete?

### The control plane should not do

- direct repository mutation as its main behavior
- raw code authoring for task execution
- final acceptance without evidence returned by execution
- implicit prompt invention per run without a policy record

---

## 6.3 Execution Core

The execution core owns **task-local execution**.

It receives a single `TaskPacket` and tries to produce a structured terminal result.

### Responsibilities

- build execution context for one task
- assemble concrete prompts from policy + local context
- perform code generation or code modification
- run tools, tests, linting, and validators
- classify local failure causes
- attempt bounded local repair
- run review and verification passes
- emit structured evidence and a final `ExecutionResult`

### Questions the execution core answers

- Given this task packet, can the task be completed successfully?
- If not, what specifically failed?
- What evidence supports the conclusion?
- What next action should the control plane consider?

### The execution core should not do

- reprioritize the backlog
- change portfolio-level retry budgets
- declare the whole workflow done
- modify global orchestration policy

---

## 6.4 Why this is not one giant loop

A single loop seems simpler at first:
- pick task
- generate code
- test
- review
- retry
- pick next task

But it collapses multiple qualitatively different concerns into one mechanism:
- global planning
- local execution
- failure recovery
- approval / classification
- task prioritization
- policy management

That creates a god-loop with poor boundaries.

The two-layer design is better because:

1. **Global and local failures are different**
   - local: tests failed, tool crashed, patch invalid
   - global: wrong task chosen, retry policy wrong, dependencies unresolved

2. **Prompt policy and code generation should not be conflated**
   - choosing the recipe is different from running it

3. **Execution should be made repeatable**
   - the inner loop should be boring and testable

4. **Workflow policy should remain inspectable**
   - outer-loop decisions should be explicit and durable

5. **The system scales better to many tasks**
   - once there are dependencies, budgets, parallel branches, and escalations, an outer control plane becomes necessary

---

## 7. State-machine model

## 7.1 Control-plane state machine

```text
IDLE
  -> INGEST_WORK
  -> NORMALIZE_TASKS
  -> PRIORITIZE
  -> SELECT_TASK
  -> PREPARE_TASK_PACKET
  -> DISPATCH_TO_EXECUTION_CORE
  -> INGEST_RESULT
  -> CLASSIFY_RESULT
     -> COMPLETE
     -> RETRY_LATER
     -> SPLIT_TASK
     -> ESCALATE
     -> BLOCKED
     -> ABANDON
  -> UPDATE_GLOBAL_STATE
  -> SELECT_NEXT_TASK
```

### Notes

- This is the **outer workflow machine**
- It may manage one task or many
- It should be durable across process restarts
- Its state transitions should be auditable

## 7.2 Execution-core state machine

```text
RECEIVE_TASK_PACKET
  -> BUILD_EXECUTION_CONTEXT
  -> INSTANTIATE_PROMPTS
  -> EXECUTE_ATTEMPT
  -> RUN_VALIDATION
     -> PASS -> REVIEW_OR_VERIFY
     -> FAIL -> DIAGNOSE_FAILURE
                -> REPAIR_ATTEMPT
                -> REVALIDATE
  -> TERMINALIZE_RESULT
  -> RETURN_EXECUTION_RESULT
```

A more concrete version:

```text
RECEIVE_TASK_PACKET
  -> BUILD_CONTEXT
  -> BUILD_ATTEMPT
  -> TEST / LINT / VALIDATE
     -> PASS -> REVIEW
     -> FAIL -> DIAGNOSE
                -> REPAIR
                -> RE-TEST
  -> VERIFY
  -> PACKAGE_RESULT
  -> RETURN
```

### Notes

- This is the **inner task machine**
- It should be bounded by policy set by the control plane
- It is allowed to retry locally, but only within explicit limits

---

## 8. LLM call placement and prompt management

This is one of the most important design boundaries in the system.

## 8.1 Principle

LLM calls exist in both layers, but for different reasons.

### Control-plane LLM calls
Used for **orchestration intelligence**:
- task decomposition
- dependency inference
- failure classification at workflow level
- retry vs split vs escalate decisions
- prompt-family selection
- model routing decisions
- task-packet synthesis
- summarization for operators

### Execution-core LLM calls
Used for **artifact production and task-local reasoning**:
- code generation
- code editing
- writing tests
- producing fixes from failure logs
- implementation review
- verification summaries
- minimal repair patches

## 8.2 Hard rule

- **Actual code-generation calls belong in the execution core**
- **Prompt policy and workflow policy belong in the control plane**

That means:
- the control plane chooses the prompt family, role, model, and budget
- the execution core instantiates the concrete prompt with task-local context and runs it

## 8.3 Prompt policy vs prompt instantiation

This distinction should be explicit in the implementation.

### Prompt policy = control plane
Owns:
- prompt family selection
- role definitions
- model selection
- budget and timeout selection
- retry-mode variants
- task-class-specific instruction packs
- review strictness
- security mode and allowed tool scope

### Prompt instantiation = execution core
Owns:
- injecting task packet contents
- injecting code context
- injecting test failures / logs / diffs
- injecting previous attempt evidence
- constructing the exact prompt body used for one attempt

### In short

- **Control plane chooses the recipe**
- **Execution core cooks the meal**

## 8.4 Prompt-management principles

1. Prompt families should be versioned.
2. Every execution run should record which prompt policy was used.
3. Retry prompts should not silently drift from initial prompts.
4. Prompt construction should be inspectable after the fact.
5. Prompt assembly should be deterministic given:
   - task packet
   - policy snapshot
   - attempt history
   - selected context inputs
6. The system should distinguish between roles such as:
   - builder
   - fixer
   - reviewer
   - verifier
   - summarizer

## 8.5 Why this matters

Without this split, systems tend to degrade into:
- ad hoc prompts
- invisible retry logic
- poor auditability
- self-delusion where the same loop builds and approves with weak evidence

---

## 9. Core data contracts

## 9.1 TaskPacket

A `TaskPacket` is the control plane’s contract to the execution core.

It should contain at least:

```json
{
  "task_id": "T-142",
  "goal": "Fix failing login refresh logic",
  "task_type": "bugfix",
  "repo": "...",
  "workspace": "...",
  "acceptance_criteria": ["tests pass", "refresh token logic preserved"],
  "constraints": {
    "max_attempts": 4,
    "timeout_seconds": 1800,
    "allowed_tools": ["git", "pytest"],
    "disallowed_actions": ["force-push-main"]
  },
  "prompt_policy": {
    "family": "bugfix-standard",
    "builder_role": "builder",
    "review_role": "reviewer",
    "verifier_role": "verifier",
    "model_routing": "default"
  },
  "inputs": {
    "spec_excerpt": "...",
    "relevant_files": ["..."],
    "failing_tests": ["..."]
  }
}
```

## 9.2 ExecutionResult

An `ExecutionResult` is the execution core’s contract back to the control plane.

It should contain at least:

```json
{
  "task_id": "T-142",
  "status": "passed",
  "attempt_count": 3,
  "terminal_reason": "validation_and_review_passed",
  "failure_type": null,
  "recommended_next_action": "accept",
  "artifacts": {
    "diff": "...",
    "tests": "...",
    "logs": "...",
    "review_notes": "..."
  },
  "metrics": {
    "duration_seconds": 412,
    "tokens": 38211,
    "tool_calls": 17
  },
  "confidence": 0.84
}
```

## 9.3 Attempt record

Each task attempt should be persisted with:
- attempt id
- attempt type
- start/end timestamps
- prompt policy snapshot
- prompt instantiation metadata
- model(s) used
- files touched
- commands run
- validators run
- result classification
- pointers to artifacts

## 9.4 Attempt types

Attempt types should be typed, not implicit.

Minimum set:
- `build`
- `repair`
- `review`
- `verify`
- `revalidate`
- `integrate`
- `debug`
- `salvage`

These types matter because retry semantics should differ by type.

---

## 10. Evidence and validation model

Crucible should never reduce outcomes to “LLM said done.”

Every task should move toward closure through evidence such as:
- patch/diff
- command logs
- test output
- lint results
- static analysis output
- review report
- verification report
- artifact metadata

### Validation layers

1. **Execution validation**
   - tools ran
   - commands completed
   - workspace is consistent

2. **Correctness validation**
   - tests pass
   - lint/typecheck pass
   - contract checks pass

3. **Spec validation**
   - output matches stated acceptance criteria

4. **Review validation**
   - implementation quality acceptable
   - no obvious missing edge cases

5. **Security validation**
   - no unsafe changes introduced where applicable

The exact stack can vary by task, but the runtime should know which validators were required and whether each one passed.

---

## 11. Failure taxonomy

Crucible needs an explicit failure taxonomy because retry policy depends on failure type.

Minimum categories:
- `test_failure`
- `lint_failure`
- `typecheck_failure`
- `tool_failure`
- `environment_failure`
- `timeout`
- `spec_ambiguity`
- `missing_dependency`
- `review_rejection`
- `security_rejection`
- `integration_conflict`
- `non_reproducible_failure`
- `resource_budget_exceeded`
- `blocked_by_external_state`

### Principle

Not every failure should consume the same retry budget.

For example:
- environment failures may trigger re-run or repair of setup without consuming a full build retry
- review rejection may trigger a typed repair path, not full restart
- spec ambiguity may trigger escalation rather than random retry

---

## 12. Feature set ordered by priority and problem solved

This section is intentionally ordered by product priority, not implementation convenience.

## Priority 1 — Deterministic task execution with durable state

### Problem it solves
Current agentic flows lose state, forget what happened, and cannot cleanly resume after interruption.

### Required features
- durable run manifest
- durable attempt records
- resumable execution
- artifact persistence
- terminal status classification
- CLI and API visibility into run state

### Why it matters
Without this, Crucible is just a thin wrapper over ephemeral agent runs.

---

## Priority 2 — Clear control-plane vs execution-core split

### Problem it solves
Single-loop systems become unmaintainable and impossible to reason about as complexity grows.

### Required features
- explicit control-plane interfaces
- explicit execution-core interfaces
- `TaskPacket` and `ExecutionResult` contracts
- outer vs inner state machine separation
- policy handoff into execution

### Why it matters
This is the architecture that prevents the system from collapsing into a god-loop.

---

## Priority 3 — Typed retries and failure-aware continuation

### Problem it solves
Most agent systems either retry blindly or stop prematurely.

### Required features
- failure taxonomy
- typed attempts
- bounded local repair loops
- policy-aware continuation logic
- terminal reason classification

### Why it matters
This is how Crucible actually drives tasks to closure rather than simply recording failures.

---

## Priority 4 — Prompt policy management

### Problem it solves
Prompt drift makes systems opaque, inconsistent, and hard to improve.

### Required features
- prompt-family registry
- prompt policy snapshots per run
- role-based prompt selection
- deterministic prompt instantiation metadata
- auditability of which prompt policy produced which result

### Why it matters
Prompt management is architecture, not prompt engineering garnish.

---

## Priority 5 — Evidence-first validation pipeline

### Problem it solves
Self-grading systems overstate completion and under-detect defects.

### Required features
- validator stack declaration per task
- review/verify passes
- structured artifact capture
- acceptance criteria tracking
- evidence-based terminalization

### Why it matters
Crucible should be trusted because it returns evidence, not because it sounds confident.

---

## Priority 6 — Multi-task orchestration and dependency handling

### Problem it solves
Useful real workflows contain multiple tasks with sequencing and dependencies.

### Required features
- backlog model
- dependency graph
- task splitting
- blocked-state handling
- task-selection policy

### Why it matters
This is what turns Crucible from a task runner into a real workflow substrate.

---

## Priority 7 — Human steering and approval gates

### Problem it solves
Some decisions should remain operator-controlled, especially for risky changes.

### Required features
- pause / resume / cancel
- operator notes
- escalation events
- optional approval checkpoints
- inspectable run timeline

### Why it matters
A system trusted in real workflows needs good human control surfaces.

---

## Priority 8 — Model and executor abstraction

### Problem it solves
The system should not be tied to one model or one coding agent forever.

### Required features
- model routing abstraction
- role-to-model mapping
- executor adapter layer
- support for different coding engines behind the execution core

### Why it matters
This keeps Crucible structurally durable as the underlying model landscape changes.

---

## 13. Interaction model

Crucible should support these interaction patterns:

### 13.1 Human starts work
- human or upstream system defines goal
- control plane normalizes into task packet(s)
- execution core runs task(s)
- results are observable in CLI/API/chat

### 13.2 Human inspects progress
- inspect current state
- inspect attempt history
- inspect artifacts and failure reason
- inspect next recommended action

### 13.3 Human intervenes
- pause
- resume
- cancel
- modify policy
- escalate
- supply clarification

### 13.4 Upstream orchestration uses Crucible as a substrate
- external control plane or orchestrator creates task packets
- Crucible executes them
- external system consumes structured results

This is important: Crucible should be usable both as:
- a product with its own control-plane logic
- a reusable execution runtime under a different orchestrator

---

## 14. Execution semantics

## 14.1 What “done” means

A task is done only when the execution core emits a terminal result supported by required evidence.

### Valid terminal states
- `passed`
- `failed`
- `blocked`
- `escalated`
- `abandoned`

### `passed` requires
- required validators passed
- review/verify status satisfied for that task type
- artifacts persisted
- terminal reason recorded

## 14.2 Local retry semantics

The execution core may retry locally when:
- failure type is repairable
- retry budget remains
- no control-plane escalation is required first

Examples:
- failing tests after codegen -> repair loop
- linter failure -> local fix + revalidate
- review rejection -> repair + re-review

## 14.3 Escalation semantics

Execution should escalate when:
- spec is ambiguous
- dependency is missing
- repeated failures indicate policy mismatch
- approval is required
- resource limits prevent meaningful continuation

---

## 15. Storage model

Crucible should persist enough information to:
- resume safely
- audit what happened
- compare policies across runs
- expose useful status externally

### Minimum persisted objects
- `RunManifest`
- `TaskRecord`
- `AttemptRecord`
- `PolicySnapshot`
- `ArtifactIndex`
- `EventLog`
- executor adapter state

### Persistence principles

1. Disk state is authoritative for recovery.
2. In-memory state is a cache, not the source of truth.
3. Restarts should not require chat history to reconstruct run state.
4. Artifacts should be referenceable from results and status views.

---

## 16. API and CLI shape

Crucible should remain library-first with thin interfaces above it.

### Library-first requirement
The core orchestration/execution logic must live in library code, not only in CLI wrappers.

### Minimum CLI surface
- `run`
- `status`
- `watch`
- `resume`
- `cancel`
- `lint-plan` or equivalent preflight
- `artifacts`

### Minimum API surface
- create run / submit task(s)
- get run status
- get task status
- get attempt history
- get artifacts
- issue operator action
- resume / pause / cancel

---

## 17. Testing strategy

The architecture should be testable in layers.

## 17.1 Unit tests

- state machine transitions
- failure taxonomy classification
- prompt policy selection
- prompt instantiation logic
- result terminalization logic
- retry-budget accounting

## 17.2 Integration tests

- run store durability
- resume after interruption
- artifact persistence
- executor adapter interaction
- validator pipeline behavior

## 17.3 Scenario tests

- simple bug fix passes first try
- bug fix fails tests then repairs successfully
- review rejection then repair then pass
- spec ambiguity triggers escalation
- missing dependency triggers blocked state
- timeout resumes correctly

## 17.4 Golden-policy tests

Prompt policy and result contracts should have snapshot-style tests so architectural drift is visible.

---

## 18. Security and governance principles

Even though Crucible is execution-focused, governance still matters.

### Principles
- least-necessary tool access per task
- policy-defined dangerous action handling
- explicit approval hooks for risky actions
- immutable event log for critical state transitions
- inspectable artifact provenance

Crucible should not assume that all tasks are equally safe.
It should allow stronger policy for:
- production repos
- security-sensitive fixes
- release branches
- infrastructure changes

---

## 19. Phased execution plan

This section defines the implementation sequence.

## Phase 1 — Runtime foundation

### Goal
Create a durable, resumable execution substrate.

### Scope
- run manifest
- task record
- attempt record
- artifact persistence
- event log
- terminal statuses
- CLI status/watch/resume basics

### Exit criteria
- interrupted runs can resume safely
- run state survives process restart
- artifacts are persisted and discoverable
- terminal states are explicit and inspectable

### Why first
Without this, everything else is built on sand.

---

## Phase 2 — Execution core for a single task

### Goal
Implement the inner task state machine for one task packet.

### Scope
- `TaskPacket` intake
- execution context construction
- one build attempt
- validator execution
- `ExecutionResult` packaging
- bounded local repair loop

### Exit criteria
- a single bug-fix task can run end-to-end
- failure is classified with evidence
- repair loop can succeed or terminate cleanly
- results are structured, not conversational only

### Why second
This creates the minimum useful execution engine.

---

## Phase 3 — Prompt policy system

### Goal
Make prompt management explicit and durable.

### Scope
- prompt-family registry
- role definitions
- policy snapshots
- model routing abstraction
- prompt-instantiation tracing

### Exit criteria
- each run records which prompt policy was used
- retry prompts are derived explicitly, not ad hoc
- builder/reviewer/verifier roles are separable

### Why third
This turns LLM usage from hidden behavior into system architecture.

---

## Phase 4 — Review, verification, and failure taxonomy

### Goal
Strengthen correctness and continuation logic.

### Scope
- typed attempt categories
- failure taxonomy
- review pass
- verification pass
- terminal reason classification
- policy-aware retry handling

### Exit criteria
- failures are classified into meaningful categories
- review rejection and test failure take different continuation paths
- `passed` requires validator + review/verify evidence as configured

### Why fourth
This is where Crucible starts becoming trustworthy rather than merely functional.

---

## Phase 5 — Control plane for multi-task workflows

### Goal
Implement the outer workflow machine.

### Scope
- backlog model
- task prioritization
- dependency handling
- blocked-state handling
- split/escalate/retry-later decisions
- task-to-execution dispatch

### Exit criteria
- multi-task workflows can be represented and progressed
- blocked tasks do not stall unrelated tasks
- execution results drive explicit control-plane transitions

### Why fifth
This unlocks real workflow orchestration without polluting the execution core.

---

## Phase 6 — Human steering and operator controls

### Goal
Make the system operable in real use.

### Scope
- pause/resume/cancel
- operator notes
- escalation events
- status timeline
- policy override hooks where safe

### Exit criteria
- an operator can inspect and steer active runs
- escalations are visible and actionable
- operator actions are persisted in the event log

### Why sixth
A production-facing runtime needs excellent control surfaces.

---

## Phase 7 — Integration hardening and scale-up

### Goal
Make Crucible robust as a general substrate.

### Scope
- adapter abstraction for multiple executors
- improved model routing
- richer artifact indexing
- concurrency-safe workflow handling
- performance tuning
- integration docs and examples

### Exit criteria
- Crucible can support multiple execution backends cleanly
- control-plane and execution-core boundaries remain intact under scale
- documentation is sufficient for external integrators

### Why seventh
Only after the architecture is proven should we widen the matrix of backends and usage modes.

---

## 20. MVP definition

The MVP is **not** “fully autonomous software factory.”

The MVP is:

> A durable runtime that can execute a single coding task through build, validate, repair, review, and terminal result classification with explicit evidence and resumability.

### MVP capabilities
- durable run state
- one-task execution core
- bounded local repair loop
- structured result contract
- prompt policy recording
- validator + review evidence
- CLI/API status visibility

### MVP intentionally excludes
- complex multi-team planning
- highly parallel portfolio orchestration
- advanced approval routing
- every executor backend under the sun

That narrower MVP is honest, valuable, and architecturally correct.

---

## 21. Crisp design conclusions

1. **Crucible should not be one loop.**
   - It should be an outer control plane plus inner execution core.

2. **These are two different state machines.**
   - control plane = workflow-level state machine
   - execution core = task-level state machine

3. **The execution core is invoked as one action inside the control plane.**
   - not a sibling with overlapping responsibility

4. **Actual codegen LLM calls belong in the execution core.**
   - that is where task-local artifact production happens

5. **Prompt policy belongs in the control plane.**
   - that is where model/role/policy selection should live

6. **Prompt instantiation belongs in the execution core.**
   - local context should be assembled there for each attempt

7. **Evidence must be first-class.**
   - Crucible should return structured outcomes supported by artifacts

8. **Retries must be typed and policy-aware.**
   - not all failures should trigger the same continuation path

9. **The architecture should scale from single-task execution to multi-task orchestration without redesign.**

---

## 22. What success looks like

Crucible is successful when a user can truthfully say:

- I can submit a coding task and know exactly what state it is in.
- If the process dies, I can resume without guessing.
- If the task fails, I know why.
- If the task is repairable, the system repairs it within policy.
- If the task is ambiguous or blocked, the system says so explicitly.
- I can inspect the evidence, not just the chat summary.
- The orchestration logic is understandable because task execution and workflow control are clearly separated.

That is the bar for v7.1.
