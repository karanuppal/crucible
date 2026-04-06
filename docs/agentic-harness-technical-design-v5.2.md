# Agentic Harness Technical Design v5.2

**Status:** Draft for review
**Date:** 2026-04-05
**Derived from:** `docs/agentic-harness-prd-v5.2.md`
**Role of this document:** If approved, this becomes the implementation basis for v5.2.

---

## 1. Purpose and Design Scope

This document defines the implementation architecture for v5.2 of Agentic Harness.

It is the technical answer to the PRD and is intended to be implementation-driving, not merely descriptive. The harness is designed as a general architecture for reliable, long-running software execution, with OpenClaw as the first implementation environment.

This design assumes:
- v5.2 must work **without** Claude Code, Codex, or any specialized coding harness
- coding harnesses may later be integrated as optional accelerators
- sub-agents are the default execution unit for real work
- deterministic code should own repeatable orchestration, state, and gating

---

## 2. Requirement Traceability

| PRD Requirement | Technical Response |
|---|---|
| Chat-native delegation | Intent intake + orchestration layer centered on Millie in chat |
| Spec-ambiguity gate | Dedicated ambiguity analysis stage with structured outputs |
| Sub-agent-first execution | Run graph + role templates + spawn policy + salvage behavior |
| Sub-agent management cluster | Sub-agent controller + run ledger + visibility surfaces + cleanup |
| Existing-project support | Repo intake + branch/worktree isolation + task graph |
| Greenfield bootstrap support | Bootstrap policy + repo creation + CI baseline + first-working-version gate |
| Common execution interface | Backend-agnostic executor abstraction |
| Validation and gating | Validation ladder + evidence map + completion gate |
| Spec-traceable completion | Criteria-linked evidence records |
| Long-run task continuity | Persistent build/project state + resumable run model |
| Hybrid memory model | Host memory separated from harness-owned project ledger |
| Resource-aware scheduler | Machine profile + intensity classes + adaptive concurrency heuristics |
| Human interruptibility | Queryable state + steering commands + stop/kill semantics |
| Explicit failure handling | Failure taxonomy with required next actions |
| Anti-loop protection | Circuit breaker + rejection ledger |

---

## 3. System Overview

### 3.1 Major layers
1. **Conversation / control layer**
   - chat interaction with user
   - status presentation
   - clarification and steering

2. **Planning / orchestration layer**
   - converts user intent into specs, tasks, and execution plans
   - chooses when to proceed, clarify, recover, or escalate

3. **Deterministic control layer**
   - state machine
   - scheduler
   - run ledger
   - validation bookkeeping
   - artifact tracking

4. **Execution layer**
   - sub-agents as primary workers
   - inline execution for trivial deterministic actions
   - optional future accelerator backends

5. **Project memory / evidence layer**
   - project ledger
   - lessons
   - validation evidence
   - artifact refs
   - resumable run history

### 3.2 Main operating stance
Millie should primarily be:
- planner
- orchestrator
- reviewer interface
- state interpreter
- escalation point

Sub-agents should primarily be:
- builders
- reviewers
- debuggers
- researchers
- integrators
- salvage workers

---

## 4. Unified Workflow Model

### 4.1 Existing-project path
1. inspect repository
2. run ambiguity analysis
3. create/update spec
4. decompose into tasks
5. execute tasks through run graph
6. validate and integrate
7. update ledger and summarize

### 4.2 Greenfield path
1. clarify project intent enough to bootstrap
2. choose baseline stack and scaffold defaults
3. create local repo
4. create remote GitHub repo if credentials are available
5. install minimum CI baseline
6. produce first working version
7. continue through the same loop as existing-project mode

### 4.3 Greenfield defaults
Unless the spec requires otherwise, greenfield bootstrap should autonomously choose:
- a reasonable stack based on requested platform/language
- a minimal project skeleton
- a README
- formatter/linter baseline if ecosystem-standard
- at least one runnable local entrypoint
- at least one CI job covering install + test/build

If the requested product is too underspecified to choose responsibly, the ambiguity gate should ask a targeted clarification question instead of stalling indefinitely.

### 4.4 First working version criteria
A greenfield project reaches “first working version” when:
- repo exists locally
- remote repo exists when credentials are available
- project scaffold is coherent
- local run/build succeeds for the requested project type
- minimal CI baseline is configured
- at least one proof artifact exists

---

## 5. Spec and Ambiguity System

### 5.1 Ambiguity gate
Before substantial implementation work, run ambiguity analysis against:
- undefined key terms
- missing acceptance criteria
- unclear scope boundaries
- hidden dependencies
- unresolved platform assumptions
- contradictions

### 5.2 Ambiguity outputs
The ambiguity gate must output one of:
- **CLEAR**
- **CLARIFY**
- **SPLIT**
- **DEFER**

### 5.3 Default autonomy policy
The harness should proceed autonomously when:
- there is a standard safe default
- the choice is reversible
- the choice does not materially redefine the product ask
- the result can still be validated against the spec

The harness should ask the user when:
- multiple materially different product interpretations exist
- the choice changes delivery scope significantly
- credentials/external access are required and missing
- a blocking dependency cannot be substituted

This is the core “minimal input, maximal work output” policy.

### 5.4 Spec discipline
The harness should preserve the following portable rules:
- workers read the source spec, not a paraphrase
- reviewers generate their own checklist from the spec
- bug-fix tasks require reproduce → fix → verify
- completion requires evidence tied to criteria, not just a builder claim

---

## 6. Sub-Agent-First Execution Architecture

### 6.1 Run graph model
Execution is modeled as a run graph, not a flat list of workers.

A run may:
- spawn child runs
- consume artifacts from sibling/parent tasks via the ledger
- return findings, code, or evidence into a parent integration step

### 6.1.1 Parent / child ownership rules
- Every child run has exactly one parent run or one owning task if spawned by the orchestrator directly.
- Parent runs are responsible for interpreting child outputs, but child completion does not automatically mark the parent complete.
- A parent may be complete only when all blocking children are complete, killed, or explicitly detached.
- Non-blocking children may continue after the parent if they are explicitly reattached to another owning task or integration run.

### 6.1.2 Cancellation propagation
- Cancelling a parent run should cancel all blocking children by default.
- Non-blocking children may survive parent cancellation only if the controller explicitly marks them detached and reassigns ownership.
- Integration and review runs attached to a cancelled task should be cancelled unless their outputs are still needed by another surviving task.

### 6.1.3 Partial-success semantics
- A run may end in `complete`, `failed`, or `partial`.
- `partial` means usable artifacts were produced but the owning task is not yet complete.
- Partial outputs must be recorded in the ledger and become inputs for salvage, integration, or follow-on runs.

### 6.1.4 Retry boundaries
- Retries should attach to the task, not blindly to the exact same run shape.
- After repeated failure, the controller should prefer changing role, backend, task shape, or decomposition rather than respawning an identical worker.
- Review and integration runs should not be retried as builders; they should fail back into task orchestration with explicit findings.

### 6.2 Logical worker roles
Support at least:
- **builder** — implements changes
- **reviewer** — checks against spec + evidence
- **debugger** — investigates failing behavior
- **researcher/scout** — explores codebase or external docs
- **integrator** — merges parallel outputs and resolves collisions
- **salvage worker** — resumes or completes partial work after timeout/failure

### 6.3 Spawn policy heuristics
Default to spawning a worker when:
- task is multi-file or nontrivial
- task requires an independent perspective (review, security, research)
- task can run in parallel with other work
- task may take long enough that isolation and visibility matter

Stay inline when:
- work is tiny and deterministic
- action is state bookkeeping
- action is a simple edit or command needed to unblock orchestration

### 6.4 Fan-out / fan-in patterns
The harness should support:
- **fan-out build:** multiple independent builders in separate worktrees
- **fan-out review:** separate reviewer and security/adversarial reviewer
- **fan-in integration:** dedicated integrator validates merged results and resolves overlap

### 6.5 Reviewer separation
Reviewer runs must be context-isolated from builder runs except for:
- spec
- diff/artifacts
- validation outputs

This is required to avoid rubber-stamping.

### 6.6 Timeout salvage patterns
When a run times out, the controller should choose one of:
- resume same task with a salvage worker
- split remaining work into smaller tasks
- absorb small remainder inline
- escalate if the failure class requires user input

Timeout alone is not a reason to stop the project.

### 6.7 Active-run visibility
The harness must maintain a user-queryable view of:
- active runs
- role of each run
- current task association
- last progress timestamp
- current status
- blocked reason if any

---

## 7. Execution Backend Interface

### 7.1 Purpose
The harness must work without specialized coding harnesses now while remaining able to plug them in later.

### 7.2 Interface shape

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

### 7.3 Initial backends
- **OpenClaw sub-agent backend** — primary v5.2 backend
- **Inline deterministic backend** — tiny actions
- **Future Claude Code backend** — optional accelerator
- **Future Codex backend** — optional accelerator

### 7.4 Design rule
Everything above this layer must rely on capabilities and artifact contracts, not backend-specific assumptions.

---

## 8. State Contracts

### 8.1 ProjectState
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

### 8.2 BuildState
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

### 8.3 TaskState
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

### 8.4 RunState
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

### 8.5 ValidationState
Tracks validation evidence.

Required fields:
- `validationId`
- `taskId`
- `criterionResults[]`
- `gateResults[]`
- `artifactRefs[]`
- `verdict`

### 8.6 IntegrationState
Tracks merge/fan-in work.

Required fields:
- `integrationId`
- `inputTaskIds[]`
- `inputRunIds[]`
- `conflicts[]`
- `mergeOrder[]`
- `finalArtifacts[]`
- `status`

---

## 9. Ledger, Event, and Artifact Model

### 9.1 Append-only ledger
The harness should maintain an append-only project ledger capturing meaningful transitions.

### 9.2 Event schema
Each ledger event should include:
- `timestamp`
- `projectId`
- `buildId`
- `taskId` (optional)
- `runId` (optional)
- `eventType`
- `payload`

Event types should include at minimum:
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

### 9.3 Artifact refs
Every artifact should be stored via a typed reference:
- `spec`
- `diff`
- `test-output`
- `build-log`
- `screenshot`
- `sample-output`
- `review-report`
- `integration-report`

Artifacts should follow a stable convention:
- raw outputs are preserved where practical
- summaries reference raw outputs rather than replacing them
- artifacts are immutable once attached to a completed run
- later runs may reference earlier artifacts but should not overwrite them

### 9.4 Consume / produce flow
The harness should make phase boundaries explicit:

| Phase | Consumes | Produces |
|---|---|---|
| Ambiguity | user intent, project context | ambiguity result, clarification questions |
| Spec | clarified intent | spec artifact |
| Decomposition | spec artifact | task states with verification triples |
| Execution | task state + run context | code/artifacts/run summaries |
| Validation | code/artifacts/spec | validation state + evidence refs |
| Review | spec + diff + validation outputs | review report |
| Integration | task outputs + review results | merged output + integration report |
| Completion | integrated output + validation evidence | completion summary |

This restores the explicit artifact chain needed for reliable orchestration.

---

## 10. Failure Taxonomy

The harness must classify failures explicitly rather than treating all failures as retries.

### 10.1 Failure classes and actions

| Failure Class | Meaning | Required Next Action |
|---|---|---|
| `ambiguity_block` | spec/request is materially ambiguous | ask user targeted question |
| `environment_block` | local environment/tooling is broken | fix environment, rerun affected stage |
| `missing_dependency` | credential, service, or external prerequisite missing | request/provide missing dependency path |
| `architecture_mismatch` | current project architecture cannot support requested change cleanly | stop local task retries and propose architecture revision |
| `model_limitation` | worker repeats weak/incorrect reasoning patterns | switch role/model/backend or split task before retry |
| `validation_failure` | implementation exists but validation failed | repair based on failing evidence |
| `integration_conflict` | parallel outputs collide | route to integrator |
| `loop_detected` | no-progress or repeated same-error behavior | trip circuit breaker and force non-identical next step |

### 10.2 Budget semantics
Environment and missing-dependency failures should not be treated like ordinary implementation retries.

### 10.3 User-facing effect
Failure class determines:
- whether the harness continues autonomously
- whether it asks the user something
- what kind of summary/update the user sees

---

## 11. Anti-Loop Protections

### 11.1 Circuit breaker
The harness should trip a circuit breaker when any of these conditions hold:
- repeated same-error signature beyond threshold
- repeated no-progress iterations beyond threshold
- repeated low-value output / obvious looping behavior

### 11.2 Rejection ledger
For each task, maintain a rejection ledger capturing:
- attempted approach
- why it failed
- what evidence invalidated it
- what lesson should constrain the next attempt

This prevents re-attempting known-bad fixes without new evidence.

### 11.3 Recovery after breaker
When breaker trips, next action must be one of:
- split task smaller
- change backend/model/role
- switch from builder to debugger
- escalate if ambiguity/architecture issue is exposed

---

## 12. Validation and Review System

### 12.1 Validation ladder
Primary levels for v5.2:
1. static checks
2. targeted tests
3. local build/run checks
4. proof/demo artifacts
5. CI validation

### 12.1.1 Must-pass vs informational gates
- A task must declare which gates are **must-pass** and which are **informational**.
- Must-pass gates block completion.
- Informational gates may ship findings into the completion summary without blocking, but only if the spec allows that level of evidence.
- For normal implementation tasks, targeted tests and local build/run checks should usually be must-pass when available.

### 12.2 Verification triple
Each task should define:
- what to build
- how to verify it
- what failure looks like

### 12.3 Bug-fix discipline
Bug-fix tasks require:
- reproduce
- fix
- verify

This should be encoded as a task type, not left to memory.

### 12.4 Deterministic audit mindset
Review/integration should check at minimum:
- spec criteria coverage
- validation evidence presence
- docs impact if applicable
- obvious regression or missing-path risk
- whether tests would fail if implementation were absent or broken

### 12.4.1 Anti-vacuity rule
A validation set is insufficient if it would still pass after removing or clearly breaking the claimed implementation. When that risk is obvious, the task cannot be marked complete until stronger evidence exists.

### 12.5 Reviewer outputs
Reviewer should produce:
- criterion-by-criterion compliance assessment
- likely escaped defect
- untested path
- verdict

### 12.6 Completion semantics
A task may be marked complete only when:
- all required deliverables exist
- all must-pass gates have passed or are explicitly unavailable for legitimate reasons
- any informational-only gaps are surfaced in the task summary
- review findings are either resolved or accepted as non-blocking with explicit rationale

A build may be marked complete only when:
- required task outputs are integrated
- post-integration validation has run
- no unresolved blocking failure class remains

---

## 13. Scheduler and Resource Policy

### 13.1 Machine study
At setup, record:
- CPU cores
- RAM
- swap
- free disk
- GPU availability if relevant

### 13.2 Task intensity classes
Each task/run should be classified as:
- **light** — review, research, docs, simple edits
- **medium** — moderate coding, normal tests
- **heavy** — large builds, heavy test suites, parallel integration, compile-intensive tasks

### 13.3 Qualitative scheduling policy
The scheduler should:
- preserve meaningful CPU headroom
- preserve memory headroom to avoid swap thrash
- reduce concurrency for heavy tasks
- allow higher parallelism for light analysis/review work
- prefer isolated worktrees for parallel builders
- avoid parallelizing tightly coupled tasks unnecessarily

### 13.4 Concrete heuristic starting point
Initial heuristic may be simple, for example:
- never schedule heavy tasks to consume all effective cores
- preserve at least one meaningful lane for orchestration/system responsiveness
- reduce builder concurrency when memory pressure rises
- allow review/research concurrency above build concurrency if they are light
- prefer reviewer/debugger lanes over spawning an additional heavy builder when the machine is near saturation

This can evolve later, but v5.2 should not be purely aspirational here.

---

## 14. Long-Run Autonomy and User Control

### 14.1 Default continuation behavior
The harness should continue autonomously by default when:
- next step is obvious from state
- failure type is repairable without clarification
- a standard default is adequate
- partial work can be salvaged productively

### 14.2 Default escalation behavior
The harness should escalate only when:
- ambiguity materially changes product direction
- external dependency is truly missing
- architecture revision needs user buy-in
- repeated failure reveals a decision the harness should not guess

### 14.3 Update cadence
During long-running work, the user should be able to expect:
- start summary
- milestone/task-complete updates
- blocker/escalation updates when required
- final completion summary

### 14.4 Query surface
The system should support answering:
- what is active now?
- what finished?
- what is blocked?
- what remains?
- which runs are doing what?

from deterministic state, not conversational memory.

---

## 15. Integration Policy

### 15.1 When an integrator is mandatory
A dedicated integrator run is mandatory when:
- multiple builder runs touch overlapping areas
- fan-out work must be merged back into one deliverable
- review findings from parallel runs must be reconciled together
- partial outputs from salvage workers need consolidation

### 15.2 Merge ordering
Merge/fan-in should prefer:
- least-dependent outputs first
- conflict-prone outputs later, once stable dependencies are in place
- review before final integration signoff when multiple branches changed the same subsystem

### 15.3 Post-integration validation
After fan-in, the harness must re-run the minimum must-pass validation set for the integrated result before the build can be considered complete.

---

## 16. OpenClaw as First Implementation Surface

### 16.1 OpenClaw-specific advantages
OpenClaw provides:
- chat surface
- sub-agent runtime
- tool access
- browser integration
- process/session primitives

### 16.2 Portable core
Portable harness concerns remain:
- state contracts
- project ledger schema
- scheduler policy
- execution backend abstraction
- validation evidence model
- failure taxonomy
- run graph semantics

This preserves the architecture as separable from the implementation surface.

---

## 17. Implementation Plan

### Phase 1: deterministic substrate
- ProjectState / BuildState / TaskState / RunState / ValidationState
- append-only ledger
- ambiguity gate output format
- failure taxonomy

### Phase 2: sub-agent management cluster
- run graph support
- role templates
- spawn/monitor/steer/kill/cleanup
- timeout salvage
- active-run visibility
- rejection ledger + circuit breaker

### Phase 3: unified project workflows
- existing-project intake
- greenfield bootstrap defaults
- repo/worktree tracking
- GitHub repo creation
- first-working-version gate

### Phase 4: validation and review
- verification triples
- validation ladder execution
- evidence mapping
- reviewer workflow
- integration and completion gates

### Phase 5: scheduling and memory
- machine profile
- intensity classification
- adaptive concurrency heuristics
- harness memory retrieval/injection
- project lessons persistence

### Phase 6: optional accelerators
- Claude Code adapter
- Codex adapter
- backend capability routing

---

## 18. Technical Design Summary

If approved, v5.2 implementation should be built around these anchor decisions:
- one harness architecture, not separate greenfield and maintenance systems
- sub-agents as the default execution primitive
- deterministic code for state, scheduling, failure handling, and validation bookkeeping
- a common execution interface so accelerators remain optional
- harness-owned project memory distinct from host conversational memory
- machine-aware scheduling instead of fixed concurrency limits
- explicit validation evidence tied back to the spec
- explicit run-graph, integration, and completion semantics so builders do not have to infer core behavior
- strong anti-loop and recovery behavior for long-running autonomy

That is the implementation spine for v5.2.
