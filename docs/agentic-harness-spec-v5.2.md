# Agentic Harness Specification v5.2

**Status:** Draft for review
**Date:** 2026-04-06
**Ground truth sources:**
- `docs/agentic-harness-prd-v5.2.md`
- `docs/agentic-harness-technical-design-v5.2.md`

**Purpose of this document:**
This is the single externally shareable specification for Agentic Harness v5.2. It combines product requirements and implementation architecture into one coherent spec. v5.2 is the source of truth for requirements and architecture. The v4.6.2 architecture document influenced the organization and flow, but not the substance where v5.2 is more specific.

---

## 1. Overview

Agentic Harness is a general harness architecture for turning chat-native delegation into reliable, long-running software execution.

The first implementation surface is OpenClaw, where Millie acts as planner, orchestrator, reviewer interface, and status surface. But the harness is not conceptually limited to OpenClaw. The architecture should remain portable and open-sourceable in concept even if the first implementation is an OpenClaw integration.

The core user promise is:

> A user should be able to send a concise description of a software project from their phone, and the system should autonomously build a functional, validated implementation with minimal back-and-forth.

This must work for both:
- building a new project from scratch
- iterating on an existing codebase over time

The product is not “an agent that can type code.” The product is the harness around delegated software execution:
- spec-first planning
- deterministic orchestration where repeatability matters
- sub-agent-first execution
- explicit validation and review gates
- durable project continuity over long-running work

---

## 2. Product Thesis and Job to Be Done

### Primary job to be done
When a user gives Millie a substantial software task in chat, the system should manage the work end-to-end so the user can trust a working, validated result without manually driving implementation.

### Expanded job to be done
From a mobile-first user standpoint, the harness should let the user:
- describe a project or feature in natural language
- stay lightly involved rather than continuously involved
- inspect status, active workers, blockers, and progress at any point
- trust that the harness is managing decomposition, execution, validation, and recovery
- receive output that has been tested against a clear spec and explicit gates

### Product thesis
The system should maximize:
- work output per token of user input
- reliability of execution over long-running tasks
- confidence that resulting code matches a clear spec

---

## 3. Design Principles

These principles drive both product behavior and architecture.

1. **Sub-agents are the default execution unit.**
   Millie should mainly plan, orchestrate, monitor, review, and communicate. Real execution should be delegated liberally.

2. **One execution system should handle both greenfield and existing-project work.**
   Greenfield is bootstrap followed by the same iterative loop used for existing repos.

3. **Deterministic where possible, evidence-backed everywhere else.**
   State transitions, scheduling, bookkeeping, validation tracking, and repeatable policies should live in code, not in model interpretation.

4. **Spec clarity comes before implementation.**
   The harness should not build against ambiguous requirements.

5. **Validation is part of the product.**
   The harness does not merely write code. It produces validated code tied to a requested contract.

6. **Long-run autonomy is first-class.**
   The system should continue useful work over hours or phases, recover from interruption, and escalate only when genuinely blocked.

7. **Engine-agnostic core, optional accelerators.**
   The harness must work without Claude Code, Codex, or any specialized coding harness, while allowing future backends behind a common interface.

8. **Resource-aware parallelism beats arbitrary caps.**
   The system should use parallelism aggressively when safe, without exhausting the host.

9. **Portable best practices belong in the harness itself.**
   Reusable orchestration discipline should be encoded in the harness, not depend on environment-specific rituals.

---

## 4. Scope, User, and Success Definition

### Primary user
The primary user is a highly technical operator who:
- often initiates work from chat
- may be away from a laptop
- wants to delegate entire software projects, not pair-program interactively
- values reliability, proof, and leverage over conversation volume

### UX expectation
The system should feel like delegating to a capable technical operator for software building, not like manually driving an autocomplete system.

### Definition of “working”
For v5.2, “working” means:
- the spec is sufficiently clear
- the implementation matches the spec
- validation evidence exists
- relevant tests and checks pass
- unresolved risks or known gaps are surfaced explicitly

“Without bugs” in this spec means verified against a clear contract with evidence. It does not mean literal perfection.

---

## 5. System Overview

The architecture is organized into five layers.

### 5.1 Conversation and control layer
Responsible for:
- user interaction in chat
- clarification and steering
- status presentation
- interruption and redirect handling

### 5.2 Planning and orchestration layer
Responsible for:
- converting user intent into specs, tasks, and run plans
- deciding when to proceed, ask, recover, split work, or escalate
- attaching review, integration, and salvage behavior to tasks

### 5.3 Deterministic control layer
Responsible for:
- state machine behavior
- scheduler decisions
- run ledger and event recording
- validation bookkeeping
- artifact tracking
- completion semantics

### 5.4 Execution layer
Responsible for:
- sub-agents as primary workers
- inline deterministic actions for tiny tasks
- optional accelerator backends in the future

### 5.5 Project memory and evidence layer
Responsible for:
- project continuity
- task and run history
- lessons and rejection history
- validation evidence
- artifacts and completion records

### Operating stance
Millie should primarily be:
- planner
- orchestrator
- reviewer interface
- state interpreter
- escalation point

Workers should primarily be:
- builders
- reviewers
- debuggers
- researchers
- integrators
- salvage workers

---

## 6. Core Workflows

v5.2 supports two primary workflows that converge into one operating model.

### 6.1 Existing-project iteration
Expected flow:
1. inspect the repository and current state
2. run ambiguity analysis
3. create or update the working spec
4. decompose work into tasks
5. execute tasks through the run graph
6. validate and integrate outputs
7. update project state and summarize results

### 6.2 Greenfield bootstrap
Expected flow:
1. clarify project intent enough to bootstrap responsibly
2. choose baseline stack and scaffold defaults
3. create local repo
4. create remote GitHub repo if credentials are available
5. install minimum CI baseline
6. produce a first working version
7. continue through the same iterative loop used for existing projects

### 6.3 Greenfield defaults
Unless the spec requires otherwise, the harness should autonomously choose:
- a reasonable stack based on requested platform or language
- a minimal project skeleton
- a README
- formatter or linter baseline if ecosystem-standard
- at least one runnable local entrypoint
- at least one CI job covering install plus test or build

If the request is too underspecified to choose responsibly, the ambiguity gate should ask a targeted clarification question instead of stalling or guessing.

### 6.4 First working version criteria
A greenfield project reaches first working version when:
- a local repo exists
- a remote repo exists when credentials are available
- the scaffold is coherent
- local run or build succeeds for the requested project type
- minimal CI is configured
- at least one proof artifact exists

---

## 7. Spec and Ambiguity System

### 7.1 Why it exists
The harness should not build against ambiguity. Before substantial implementation, it must examine the request and current project state for:
- undefined key terms
- missing acceptance criteria
- unclear scope boundaries
- hidden dependencies
- unresolved platform assumptions
- contradictions

### 7.2 Ambiguity outcomes
The ambiguity stage must produce one of:
- `CLEAR`
- `CLARIFY`
- `SPLIT`
- `DEFER`

### 7.3 Default autonomy policy
The harness should proceed autonomously when:
- there is a standard safe default
- the choice is reversible
- the choice does not materially redefine the product ask
- the result can still be validated against the spec

The harness should ask the user when:
- multiple materially different product interpretations exist
- the choice would change delivery scope significantly
- credentials or external access are required and missing
- a blocking dependency cannot be substituted

### 7.4 Spec discipline rules
The harness should enforce these rules across workers:
- workers read the source spec, not a paraphrase
- reviewers generate their own checklist from the spec
- bug-fix tasks require reproduce → fix → verify discipline
- completion requires evidence tied to criteria, not merely a builder claim

---

## 8. Unified Build Loop

The harness should make phase boundaries explicit and preserve artifact flow between phases.

### 8.1 Phase sequence
1. intent intake and project inspection
2. ambiguity analysis
3. spec creation or update
4. task decomposition
5. execution
6. validation
7. review
8. integration
9. completion and summary

### 8.2 Artifact chain
Each phase consumes outputs from the prior phase and produces explicit artifacts.

- **Ambiguity** consumes user intent and project context; produces ambiguity result and any clarification questions.
- **Spec** consumes clarified intent; produces a spec artifact.
- **Decomposition** consumes the spec artifact; produces task states and verification triples.
- **Execution** consumes task state and run context; produces code, findings, and run artifacts.
- **Validation** consumes code, artifacts, and spec criteria; produces validation state and evidence refs.
- **Review** consumes spec, diff, and validation outputs; produces a review report.
- **Integration** consumes task outputs and review outputs; produces merged output and integration report.
- **Completion** consumes integrated output plus validation evidence; produces a completion summary.

### 8.3 Verification triple
Each task should declare:
- what to build
- how to verify it
- what failure looks like

This makes tasks inspectable and allows validation to be attached to intent rather than to code shape alone.

---

## 9. Sub-Agent-First Execution Architecture

### 9.1 Run graph model
Execution is modeled as a run graph rather than a flat worker list.

A run may:
- spawn child runs
- consume artifacts from sibling or parent tasks through the ledger
- return findings, code, or evidence into a parent integration step

### 9.2 Parent and child ownership rules
- Every child run has exactly one parent run or one owning task if spawned directly by the orchestrator.
- Parent runs interpret child outputs, but child completion does not automatically complete the parent.
- A parent may complete only when all blocking children are complete, killed, or explicitly detached.
- Non-blocking children may continue only if explicitly reattached to another owning task or integration run.

### 9.3 Cancellation propagation
- Cancelling a parent run should cancel all blocking children by default.
- Non-blocking children may survive parent cancellation only if explicitly detached and reassigned.
- Review and integration runs attached to a cancelled task should also cancel unless another surviving task still needs their outputs.

### 9.4 Partial-success semantics
A run may end in:
- `complete`
- `failed`
- `partial`

`partial` means usable artifacts were produced but the owning task is not yet complete. Partial outputs must be recorded in the ledger and made available for salvage or integration.

### 9.5 Retry boundaries
Retries should attach to the task, not blindly to the same run shape.

After repeated failure, the controller should prefer changing one of:
- role
- backend
- task shape
- decomposition

Review and integration runs should not be retried as builders.

### 9.6 Worker roles
v5.2 should support at least these logical roles:
- **builder** — implements changes
- **reviewer** — checks spec and evidence compliance
- **debugger** — investigates failing behavior
- **researcher/scout** — explores codebase or external docs
- **integrator** — merges parallel outputs and resolves collisions
- **salvage worker** — resumes or completes partial work after timeout or failure

### 9.7 Spawn policy heuristics
Default to spawning a worker when:
- the task is multi-file or nontrivial
- the task benefits from an independent perspective
- the task can run in parallel with other work
- isolation and visibility materially help

Stay inline when:
- the work is tiny and deterministic
- the action is state bookkeeping
- the action is a simple edit or command needed to unblock orchestration

### 9.8 Fan-out and fan-in
The harness should support:
- fan-out build with independent builders in isolated worktrees
- fan-out review with separate reviewer and adversarial reviewer lanes
- fan-in integration through a dedicated integrator when outputs collide or must be consolidated

### 9.9 Reviewer separation
Reviewer runs must be context-isolated from builder runs except for:
- the spec
- diffs or artifacts
- validation outputs

This prevents rubber-stamping.

### 9.10 Timeout salvage
When a run times out, the controller should choose one of:
- resume the same task with a salvage worker
- split the remaining work into smaller tasks
- absorb a small remainder inline
- escalate if the failure class requires user input

Timeout alone is not a reason to stop the project.

### 9.11 Active-run visibility
The harness must maintain a user-queryable view of:
- active runs
- role of each run
- current task association
- last progress timestamp
- current status
- blocked reason if any

---

## 10. Execution Backend Interface

### 10.1 Goal
The harness must work without specialized coding harnesses now while allowing optional accelerators later.

### 10.2 Interface contract

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

### 10.3 Initial backend set
- OpenClaw sub-agent backend — primary backend for v5.2
- inline deterministic backend — for tiny actions and bookkeeping
- future Claude Code backend — optional accelerator
- future Codex backend — optional accelerator

### 10.4 Design rule
Everything above this layer should rely on capabilities and artifact contracts, not backend-specific assumptions.

---

## 11. State, Ledger, and Artifact Model

The harness needs deterministic, durable state so long-running work can resume and be inspected reliably.

### 11.1 Core state contracts

#### ProjectState
Tracks long-lived project continuity.

Required fields:
- `projectId`
- `mode` (`existing|greenfield`)
- `repoPath`
- `remoteRepo`
- `activeBuildId`
- `machineProfileRef`
- `ledgerRef`
- `currentSpecRef`

#### BuildState
Tracks one implementation campaign.

Required fields:
- `buildId`
- `projectId`
- `phase`
- `specRef`
- `taskIds[]`
- `activeRunIds[]`
- `integrationStateRef`
- `validationStateRef`
- `failureSummary`

#### TaskState
Tracks a decomposed unit of work.

Required fields:
- `taskId`
- `title`
- `description`
- `roleNeeded`
- `size` (`S|M|L`)
- `dependencies[]`
- `allowedPaths[]`
- `deliverables[]`
- `verificationTriple`
- `status`
- `assignedRunIds[]`
- `rejections[]`
- `failureClass`

#### RunState
Tracks an individual worker run.

Required fields:
- `runId`
- `projectId`
- `buildId`
- `taskId`
- `parentRunId`
- `role`
- `backend`
- `model`
- `cwd`
- `worktreeRef`
- `status`
- `blockingChildren[]`
- `detachedChildren[]`
- `retryGroupId`
- `startedAt`
- `lastProgressAt`
- `artifactRefs[]`
- `summary`
- `cleanupStatus`

#### ValidationState
Tracks validation evidence.

Required fields:
- `validationId`
- `taskId`
- `criterionResults[]`
- `gateResults[]`
- `artifactRefs[]`
- `verdict`

#### IntegrationState
Tracks merge and fan-in work.

Required fields:
- `integrationId`
- `inputTaskIds[]`
- `inputRunIds[]`
- `conflicts[]`
- `mergeOrder[]`
- `finalArtifacts[]`
- `status`

### 11.2 Append-only ledger
The harness should maintain an append-only project ledger capturing meaningful transitions.

Each event should include:
- `timestamp`
- `projectId`
- `buildId`
- `taskId` when applicable
- `runId` when applicable
- `eventType`
- `payload`

Minimum event types:
- `spec.created`
- `spec.clarified`
- `task.created`
- `run.spawned`
- `run.progress`
- `run.timed_out`
- `run.killed`
- `run.salvaged`
- `validation.completed`
- `integration.completed`
- `failure.classified`
- `build.completed`

### 11.3 Artifact references
Artifacts should be stored through typed refs such as:
- `spec`
- `diff`
- `test-output`
- `build-log`
- `screenshot`
- `sample-output`
- `review-report`
- `integration-report`

Artifact rules:
- raw outputs should be preserved where practical
- summaries should point to raw outputs rather than replace them
- artifacts attached to a completed run should be immutable
- later runs may reference earlier artifacts but should not overwrite them

---

## 12. Validation and Review System

### 12.1 Validation philosophy
The validation system should follow these rules:
- do not build against ambiguity
- do not accept “looks right” as proof
- use the strongest practical validation available
- tie validation back to the spec, not just the implementation
- prefer executable local proof over theoretical confidence
- for bug fixes, require reproduce → fix → verify discipline
- when full proof is unavailable, record evidence and residual risk explicitly

### 12.2 Validation ladder
Primary validation levels for v5.2:
1. static checks
2. targeted tests
3. local build or run checks
4. proof or demo artifacts
5. CI validation

Cloud deployment is not assumed for v5.2.

### 12.3 Must-pass versus informational gates
- Each task should declare which gates are must-pass and which are informational.
- Must-pass gates block completion.
- Informational gates may be surfaced in the summary without blocking, but only if the spec allows that evidence level.
- For normal implementation tasks, targeted tests and local build or run checks should usually be must-pass when available.

### 12.4 Bug-fix discipline
Bug-fix tasks should be encoded as a task type with mandatory flow:
- reproduce
- fix
- verify

### 12.5 Reviewer outputs
A reviewer should produce:
- criterion-by-criterion compliance assessment
- one likely escaped defect
- one untested path
- a verdict

### 12.6 Anti-vacuity rule
Validation is insufficient if it would still pass after removing or clearly breaking the claimed implementation. When that risk is obvious, the task cannot be marked complete until stronger evidence exists.

### 12.7 Completion semantics
A task may be marked complete only when:
- all required deliverables exist
- all must-pass gates have passed or are explicitly unavailable for legitimate reasons
- informational gaps are surfaced in the task summary
- review findings are either resolved or accepted as non-blocking with explicit rationale

A build may be marked complete only when:
- required task outputs are integrated
- post-integration validation has run
- no unresolved blocking failure class remains

---

## 13. Failure Taxonomy and Anti-Loop Protection

The harness must classify failures explicitly rather than treating all failure as generic retry.

### 13.1 Failure classes
v5.2 should support at least these classes:
- `ambiguity_block` — the request or spec is materially ambiguous
- `environment_block` — local environment or tooling is broken
- `missing_dependency` — credential, service, or external prerequisite is missing
- `architecture_mismatch` — the current architecture cannot support the requested change cleanly
- `model_limitation` — the worker repeats weak or incorrect reasoning patterns
- `validation_failure` — implementation exists but validation failed
- `integration_conflict` — parallel outputs collide
- `loop_detected` — repeated no-progress or same-error behavior

### 13.2 Required next actions
- `ambiguity_block` → ask the user a targeted question
- `environment_block` → fix environment and rerun affected stage
- `missing_dependency` → request or document the missing dependency path
- `architecture_mismatch` → stop local retries and propose architecture revision
- `model_limitation` → change role, model, backend, or task shape before retry
- `validation_failure` → repair based on failing evidence
- `integration_conflict` → route to integrator
- `loop_detected` → trip circuit breaker and force a non-identical next step

### 13.3 Budget semantics
Environment and missing-dependency failures should not be treated like ordinary implementation retries.

### 13.4 Circuit breaker
The harness should trip a circuit breaker when any of these hold:
- repeated same-error signature beyond threshold
- repeated no-progress iterations beyond threshold
- repeated low-value or obviously looping output beyond threshold

### 13.5 Rejection ledger
For each task, maintain a rejection ledger capturing:
- attempted approach
- why it failed
- what evidence invalidated it
- what lesson should constrain the next attempt

This prevents repeated retries of known-bad approaches without new evidence.

### 13.6 Recovery after breaker
Once the breaker trips, the next action must be one of:
- split the task smaller
- change backend, model, or role
- switch from builder to debugger
- escalate if ambiguity or architecture issues were exposed

---

## 14. Scheduler and Resource Policy

### 14.1 Machine study
At setup, the harness should record:
- CPU cores
- RAM
- swap
- free disk
- GPU availability if relevant

### 14.2 Task intensity classes
Each task or run should be classified as:
- **light** — review, research, docs, simple edits
- **medium** — moderate coding, ordinary tests
- **heavy** — large builds, heavy suites, parallel integration, compile-intensive tasks

### 14.3 Scheduling policy
The scheduler should:
- preserve meaningful CPU headroom
- preserve enough memory headroom to avoid swap thrash
- reduce concurrency for heavy tasks
- allow higher parallelism for light analysis and review work
- prefer isolated worktrees for parallel builders
- avoid parallelizing tightly coupled tasks unnecessarily

### 14.4 Initial heuristic direction
A simple starting heuristic is acceptable for v5.2 if it:
- never lets heavy tasks consume all effective cores
- preserves at least one lane for orchestration and system responsiveness
- reduces builder concurrency under memory pressure
- allows more review or research concurrency than build concurrency when those runs are light
- prefers reviewer or debugger lanes over an extra heavy builder when the machine is near saturation

The scheduler in v5.2 should be practical, not merely aspirational.

---

## 15. Long-Run Autonomy and User Control

### 15.1 Default continuation behavior
The harness should continue autonomously by default when:
- the next step is obvious from current state
- the failure type is repairable without clarification
- a standard default is adequate
- partial work can be salvaged productively

### 15.2 Default escalation behavior
The harness should escalate only when:
- ambiguity materially changes product direction
- an external dependency is truly missing
- an architecture revision needs user buy-in
- repeated failure reveals a decision the harness should not guess

### 15.3 Update cadence
During long-running work, the user should be able to expect:
- a start summary
- milestone or task-complete updates
- blocker or escalation updates when required
- a final completion summary

### 15.4 Query surface
The system should be able to answer, from deterministic state rather than conversational memory:
- what is active now?
- what finished?
- what is blocked?
- what remains?
- which runs are doing what?

### 15.5 Human interruptibility
The user must be able to:
- inspect active workers
- redirect priorities
- ask for current status
- stop or reshape execution mid-flight

---

## 16. Integration Policy

### 16.1 When an integrator is mandatory
A dedicated integrator run is mandatory when:
- multiple builder runs touch overlapping areas
- fan-out work must be merged back into one deliverable
- parallel review findings must be reconciled together
- salvage outputs need consolidation

### 16.2 Merge ordering
Fan-in should generally prefer:
- least-dependent outputs first
- conflict-prone outputs later, once stable dependencies are in place
- review before final integration signoff when multiple branches changed the same subsystem

### 16.3 Post-integration validation
After fan-in, the harness must rerun the minimum must-pass validation set on the integrated result before the build can be considered complete.

---

## 17. Memory Model and Continuity

v5.2 requires a hybrid memory model with two layers.

### 17.1 Host-level continuity
Broad conversational and platform continuity supplied by the host environment.

### 17.2 Harness-owned continuity
Project and task continuity owned by the harness, including:
- execution ledger
- project state
- task history
- lessons
- rejection history
- validation evidence
- resumable run history

The important rule is separation: the harness should not rely on generic chat memory as its source of project truth.

---

## 18. OpenClaw as First Implementation Surface

### 18.1 Why OpenClaw fits
OpenClaw provides:
- the chat surface
- sub-agent runtime
- tool access
- browser integration
- process and session primitives

### 18.2 What remains portable
The following concerns should remain portable beyond OpenClaw:
- state contracts
- project ledger schema
- scheduler policy
- execution backend abstraction
- validation evidence model
- failure taxonomy
- run-graph semantics

That separation preserves the harness as an architecture, not just an integration.

---

## 19. Release Criteria for v5.2

v5.2 should be considered ready when:
- both greenfield and existing-project workflows are supported
- sub-agent orchestration is first-class rather than incidental
- the system works without Claude Code or Codex access
- the common execution interface exists and can absorb future accelerators
- project and task continuity are stored in harness-owned state
- validation gates are explicit and linked back to the spec
- failure taxonomy and anti-loop protections are implemented
- run-graph, integration, and completion semantics are explicit enough that builders do not have to infer them
- the operator can inspect, steer, and recover long-running work

---

## 20. Implementation Plan

The implementation can be staged in six phases.

### Phase 1: deterministic substrate
Build:
- state contracts
- append-only ledger
- ambiguity gate output format
- failure taxonomy

### Phase 2: sub-agent management cluster
Build:
- run graph support
- role templates
- spawn, monitor, steer, kill, cleanup
- timeout salvage
- active-run visibility
- rejection ledger and circuit breaker

### Phase 3: validation and review foundation
Build:
- verification triples
- validation ladder execution
- evidence mapping
- reviewer workflow
- integration and completion gates

### Phase 4: scheduling and memory foundation
Build:
- machine profile
- intensity classification
- adaptive concurrency heuristics
- harness memory retrieval and injection
- project lessons persistence

### Phase 5: unified project workflows
Build:
- existing-project intake
- greenfield bootstrap defaults
- repo and worktree tracking
- GitHub repo creation
- first-working-version gate
- Python as the default backend language unless the spec requires otherwise
- `uv` as the default Python package and project manager unless the spec requires otherwise

### Phase 6: optional accelerators
Build:
- Claude Code adapter
- Codex adapter
- backend capability routing

---

## 21. Non-Goals for v5.2

v5.2 does not aim to solve:
- cloud deployment orchestration across AWS, GCP, Vercel, or similar platforms
- package publishing as a core workflow
- cost optimization as the primary product objective
- dependence on Claude Code, Codex, or any specific coding harness
- OpenClaw-specific behavior as the only valid implementation model
- IDE-first human-in-the-loop development as the main interaction model

---

## 22. Success Metrics

### Primary success metrics
- delegation leverage
- autonomous completion rate
- spec-matched completion rate
- long-run reliability
- status visibility quality
- recovery quality after interruption or timeout

### Secondary success metrics
- greenfield-to-iteration continuity
- validation completeness
- scheduler quality without machine thrash
- sub-agent orchestration effectiveness, including:
  - useful parallelism
  - manageable visibility
  - low duplicate work

---

## 23. Evaluation and Benchmarkability

Benchmarkability is not the product promise, but it matters for evaluation.

The system should later be evaluable on:
- existing-repo bug-fix tasks in a SWE-bench-style setting
- greenfield bootstrap tasks
- long-running multi-step implementation tasks

Evaluation should measure not just whether a patch exists, but whether the harness:
- handled ambiguity correctly
- used sub-agents effectively
- preserved continuity over time
- produced credible validation evidence

---

## 24. Summary of Anchor Decisions

The implementation spine for v5.2 is:
- one harness architecture for both greenfield and existing-project work
- sub-agents as the default execution primitive
- deterministic code for state, scheduling, failure handling, and validation bookkeeping
- a common execution interface so accelerators remain optional
- harness-owned project continuity distinct from host conversational memory
- machine-aware scheduling instead of fixed concurrency caps
- explicit validation evidence tied back to the spec
- explicit run-graph, integration, and completion semantics
- strong anti-loop and recovery behavior for long-running autonomy

That is the merged specification for Agentic Harness v5.2.
