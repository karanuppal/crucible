# Crucible Specification v5.4

**Status:** Draft for review  
**Date:** 2026-04-07  
**Supersedes:** `docs/crucible-spec-v5.3.md` where they conflict  
**Read first with this doc:**
- `docs/crucible-spec-v5.3.md`
- `docs/agentic-harness-prd-v5.2.md`
- `docs/agentic-harness-technical-design-v5.2.md`
- `src/crucible/runtime/run_executor.py`
- `src/crucible/runtime/openclaw_tool.py`
- `src/crucible/orchestrator/orchestrator.py`
- `src/crucible/runner/run_graph.py`
- `src/crucible/runner/spawn_controller.py`
- `src/crucible/failures/taxonomy.py`

---

## 1. Why v5.4 exists

v5.3 made an important correction: it stopped Crucible from fabricating success. The current `run_executor.py` is intentionally honest. It executes verification commands itself, writes durable attempt records, and only reports success when the adapter actually returns a completed run and the expected output is present.

That was necessary, but it also exposed the remaining gap between:
- the **original product promise**: deterministic, long-running software execution with autonomous build → fail → repair → retest behavior, and
- the **current runtime reality**: a durable verifier plus task-plan runner that still depends on an outer LLM or skill to decide what to build next when validation fails.

Today, Crucible is strong at:
- plan linting
- durable run storage
- honest command execution
- status/watch/resume surfaces
- basic task/run bookkeeping

But it still does **not fully own**:
- the repair loop after failure
- deterministic selection of the next repair action
- builder / reviewer / debugger / salvage handoff policy
- failure-class-driven closed-loop progression
- attempt-level workspace lineage across retries
- evidence requirements for accepting a repair versus spawning a new attempt
- chat-surface semantics for “working on it”, “repairing”, “blocked”, and “done” as first-class runtime states

In practice, v5.3 can verify a proposed plan honestly, but it does not yet make Crucible the system that deterministically drives software work from first build attempt through validated completion.

**v5.4 exists to move the build-fail-repair-retest loop into Crucible itself.**

---

## 2. Problem statement

### 2.1 The core gap

The current runtime architecture separates:
- **plan creation** at the chat/skill layer
- **task execution + verification** inside Crucible

That split is good for natural-language interpretation, but too much recovery logic still lives outside the harness. When a build attempt fails, the embedding LLM often has to:
- interpret the failure
- decide whether it is a build failure, environment problem, test mismatch, or plan defect
- decide whether to retry, split, debug, or ask the user
- decide which role should act next
- synthesize the next task or prompt

That means the most repeatability-critical part of the product — long-running recovery — is still partly governed by conversational continuation rather than deterministic control code.

### 2.2 Why this matters

If the outer LLM owns repair policy, then the same failure can produce different outcomes depending on:
- message phrasing
- context window contents
- incidental chat history
- model drift
- whether a prior summary omitted key evidence

That weakens the main product promise. The user does not want:
- “a model that might continue sensibly if prompted again”

The user wants:
- “a harness that keeps working until it reaches a real terminal condition with evidence.”

### 2.3 Concrete v5.3 shortcomings exposed by the current code

#### A. `run_executor.py` is criterion-centric, not repair-centric
The current executor iterates through task criteria and marks tasks complete or failed based on verification results. It does **not** own:
- attempt strategy
- repair synthesis
- debug routing
- structured salvage
- re-test planning

It is an honest runner, but not yet a deterministic closed-loop software executor.

#### B. `orchestrator.py` still treats execution too coarsely
The current orchestrator has the right conceptual phases, but its execution/validation loop still effectively assumes:
- one execution pass
- one validation pass
- best-effort lesson capture

It does not encode a first-class retry/repair/salvage state machine.

#### C. Failure taxonomy exists, but next-step ownership is shallow
`taxonomy.py` maps failure classes to next actions, which is correct directionally, but there is not yet a full runtime policy layer that turns:
- failure class + attempt history + evidence state

into a deterministic next run decision.

#### D. Run graph semantics exist, but handoff semantics are underspecified
`run_graph.py` and `spawn_controller.py` define roles, parent/child structure, and timeout/cancellation basics, but not:
- when a builder failure should route to debugger instead of builder retry
- when reviewer should run before or after repair
- when salvage may inherit a workspace
- when integration is allowed to consume partial outputs
- when the circuit breaker forces decomposition rewrite instead of more retries

#### E. The chat surface watches runs, but the runtime does not yet expose the right semantic states
`openclaw_tool.py` provides `run/status/watch/resume`, but the runtime status model is still too thin for a strong mobile UX. The chat layer can report runtime state, but the runtime does not yet distinguish enough semantically meaningful sub-states such as:
- building
- repairing
- debugging
- awaiting review
- awaiting user clarification
- salvage in progress
- terminal partial with resumable path

---

## 3. v5.4 goal

Crucible v5.4 turns Crucible from a durable verifier/runtime surface into a **deterministic closed-loop software execution harness**.

Specifically, for every task in scope, Crucible should own:
1. initial attempt dispatch
2. evidence-backed validation
3. failure classification
4. deterministic next-action selection
5. repair/debug/salvage routing
6. re-execution and re-validation
7. reviewer gate
8. integration gate
9. terminal completion or explicit blocked/escalated outcome

The chat layer remains responsible for natural-language intake and user communication. Crucible becomes responsible for the execution loop itself.

---

## 4. v5.4 design principles

1. **Crucible owns recovery, not just verification.**  
   Verification without deterministic repair policy is insufficient.

2. **The outer LLM may decompose intent, but Crucible owns task closure.**  
   Once a task enters the runtime, completion, repair, retry, salvage, and blockage decisions must come from Crucible policy code.

3. **Every failure must map to a runtime action, not just a label.**  
   Failure taxonomy is only useful if it deterministically drives the next state transition.

4. **Attempts are first-class.**  
   Completion is not about “the task ran once.” It is about a bounded sequence of attempts with lineage, workspaces, evidence, and rejection history.

5. **Evidence gates every transition that claims progress.**  
   Builder claims do not advance the state machine without verifiable artifacts.

6. **Role handoffs are explicit.**  
   Builder, reviewer, debugger, salvage, and integrator are not interchangeable retries.

7. **Workspace lineage must be deterministic.**  
   Every attempt must know whether it starts fresh, inherits from a previous attempt, or consumes partial outputs through a controlled salvage path.

8. **Chat should observe runtime semantics, not invent them.**  
   The chat surface summarizes what Crucible already knows; it should not be the place where repair strategy is decided.

9. **Blocked is a product-quality state, not a vague failure.**  
   If Crucible stops, it must stop for an explicit, inspectable reason and with the exact evidence that justifies escalation.

---

## 5. What remains LLM-driven vs deterministic in v5.4

### 5.1 Still LLM-driven
These remain model-driven because they require semantic judgment or natural-language synthesis:
- user intent interpretation from chat
- ambiguity detection over underspecified product requests
- initial spec drafting or refinement
- initial task decomposition from the spec
- code generation within builder/debugger/salvage runs
- reviewer narrative analysis
- architecture revision proposals
- user-facing natural-language summaries

### 5.2 Deterministic in v5.4
These become runtime-owned and code-governed:
- task/attempt status transitions
- retry budget accounting
- failure-class-to-next-action mapping
- builder/reviewer/debugger/salvage handoff policy
- workspace inheritance policy
- evidence sufficiency gates
- circuit-breaker trip conditions
- attempt winner selection
- post-failure next-step selection
- terminal-state semantics
- chat-surface event emission contract

### 5.3 Boundary rule
The runtime may ask an LLM-powered worker to:
- implement
- analyze
- debug
- review
- integrate

But the runtime, not the worker, decides:
- whether the result counts
- whether another attempt is needed
- which role goes next
- whether the task is blocked, partial, failed, or complete

This is the core v5.4 separation.

---

## 6. Closed-loop execution model

### 6.1 New execution stance
In v5.4, a `crucible run` is not just “execute this plan.” It is:

> For each task, continue through bounded attempt loops until the task reaches a terminal runtime verdict under deterministic policy.

### 6.2 Task lifecycle
Each task moves through the following high-level lifecycle:

1. `queued`
2. `building`
3. `validating`
4. one of:
   - `reviewing`
   - `repairing`
   - `debugging`
   - `salvaging`
   - `integrating`
   - `awaiting_user`
   - `blocked`
   - `complete`

### 6.3 Task closure invariant
A task may reach `complete` only if:
- required deliverables exist
- all must-pass criteria pass on the winning attempt or winning integrated output
- required review gate passes
- no blocking failure class remains open
- evidence manifest is complete and immutable

### 6.4 Run closure invariant
A run may reach terminal `complete` only if:
- all blocking tasks are complete
- required integration is complete
- post-integration validation passes
- no task remains in repair/debug/salvage pending state

### 6.5 Runtime-owned loop
The runtime loop per task is:

1. select attempt type
2. spawn role-appropriate worker or deterministic executor
3. collect outputs and evidence
4. validate against criteria
5. classify failure or progress result
6. consult next-action policy
7. either:
   - complete
   - hand off to reviewer
   - hand off to debugger
   - synthesize repair attempt
   - salvage partial output
   - split/escalate/block
8. repeat until terminal

The user should not need to re-prompt for the normal repair loop.

---

## 7. Retry / repair / salvage state machine

### 7.1 New first-class attempt states
Each task attempt has exactly one of:
- `pending`
- `running`
- `completed_unverified`
- `validated_pass`
- `validated_fail`
- `partial`
- `blocked`
- `abandoned`
- `superseded`

### 7.2 New attempt types
Each attempt is typed as one of:
- `build`
- `repair`
- `debug`
- `review`
- `salvage`
- `integrate`
- `revalidate`

This is critical: retries are no longer generic. They are typed transitions.

### 7.3 State machine

```text
queued
  -> build attempt

build.validated_pass
  -> review attempt (if review required)
  -> complete

build.validated_fail
  -> classify failure
     -> repair attempt
     -> debug attempt
     -> awaiting_user
     -> blocked

repair.validated_pass
  -> review attempt
  -> complete

repair.validated_fail
  -> classify failure
     -> repair attempt (if budget + non-identical change allowed)
     -> debug attempt
     -> salvage attempt
     -> blocked

build.partial / repair.partial / debug.partial
  -> salvage attempt
  -> integrate attempt (if partial artifacts are sufficient and task policy allows)
  -> blocked

review.reject
  -> repair attempt
  -> debug attempt

review.accept
  -> complete

integrate.validated_fail
  -> repair attempt or debugger on merged output

any state
  -> awaiting_user if failure class requires external decision
  -> blocked if budgets exhausted or architecture mismatch exposed
```

### 7.4 Non-identical retry rule
A new repair attempt is permitted only if at least one of the following changes relative to the rejected attempt:
- prompt or instructions meaningfully change
- role changes
- backend or model changes
- workspace basis changes
- input evidence set changes
- decomposition changes

Blind respawn of the same failed shape is prohibited once a rejection is recorded.

### 7.5 Salvage semantics
Salvage is a distinct path, not a euphemism for retry.

A salvage attempt is allowed only when:
- the prior attempt produced partial artifacts, diffs, logs, or evidence
- those artifacts are recorded in the attempt manifest
- Crucible decides reusing them is lower-risk than restarting fresh

A salvage attempt must declare one of:
- `inherit_workspace`
- `replay_artifacts_into_fresh_workspace`
- `consume_partial_output_readonly`

This must be explicit in state.

### 7.6 Repair budgets
Budgets are tracked separately:
- `spawn_retry_budget`
- `build_attempt_budget`
- `repair_attempt_budget`
- `debug_attempt_budget`
- `review_rejection_budget`
- `salvage_attempt_budget`

This replaces the vague notion of “retry count.”

### 7.7 Terminal blocked conditions
A task becomes terminal `blocked` when any of the following hold:
- ambiguity requires user choice
- missing dependency cannot be substituted
- environment repair budget exhausted
- architecture mismatch confirmed
- repair/debug/salvage budgets exhausted without new legal next move
- circuit breaker trips and no approved recovery path remains

---

## 8. Builder / reviewer / debugger / salvage handoff rules

### 8.1 Builder
The builder is the default first implementation role.

A builder may hand off only via deterministic runtime decision to:
- reviewer after validation pass
- repair attempt after evidence-backed validation failure of a known fixable kind
- debugger after repeated failure, unclear root cause, or suspected diagnosis gap
- salvage after partial artifact production

Builder outputs alone never mark a task complete.

### 8.2 Reviewer
Reviewer is not a nice-to-have narrative pass. In v5.4 it becomes a structured acceptance gate.

Reviewer input contract:
- source spec
- winning diff or output set
- criterion results
- raw validation evidence
- rejection ledger

Reviewer output contract:
- criterion-by-criterion acceptance assessment
- explicit verdict: `accept | reject | escalate`
- escaped defect candidate
- untested path
- evidence sufficiency judgment

Reviewer may not:
- create new implementation artifacts as the winning output
- silently repair code
- replace validation

Reviewer rejection routes deterministically to repair or debug depending on rejection reason.

### 8.3 Debugger
Debugger is used when the runtime determines the failure is diagnostic, not merely corrective.

Debugger is mandatory when:
- the same criterion failed across two non-identical build/repair attempts
- validation failed but root cause is unclear
- environment symptoms and implementation symptoms are confounded
- reviewer rejects with “missing causal explanation” or “fix appears superficial”
- loop detector sees repeated symptom recurrence

Debugger output must include:
- root-cause hypothesis
- evidence refs supporting that hypothesis
- recommended next attempt type: `repair | environment_fix | architecture_escalation | user_clarification`

### 8.4 Salvage worker
Salvage is used when the previous attempt produced useful but incomplete work.

Salvage may:
- continue from inherited workspace
- extract a clean patch from partial workspace
- promote partial artifacts into a fresh repair attempt
- prepare outputs for integration

Salvage may not:
- declare a task complete without revalidation
- overwrite winning-attempt lineage

### 8.5 Integrator
Integrator is mandatory when:
- multiple attempt outputs need merging
- partial salvage output must combine with another winning attempt
- overlapping changes across tasks need fan-in

Integration output must itself be validated before completion.

---

## 9. Failure-class-driven next actions in v5.4

v5.4 keeps the v5.2/v5.3 taxonomy but upgrades it from advisory mapping to runtime policy.

### 9.1 Required next-action matrix

| Failure class | Trigger shape | Deterministic next action | Budget effect |
|---|---|---|---|
| `ambiguity_block` | Spec/request materially ambiguous | `awaiting_user` with targeted question packet | does not consume repair budget |
| `environment_block` | Tooling/cwd/runtime precondition broken | launch environment-fix attempt or block if environment policy disallows | does not consume build/repair budget |
| `missing_dependency` | Missing creds/service/input | `awaiting_user` or dependency-request state | does not consume build/repair budget |
| `architecture_mismatch` | Requested change conflicts with existing architecture | stop local retries; require architecture proposal/review | consumes current attempt, blocks further repair |
| `model_limitation` | repeated weak reasoning / ineffective attempts | switch role/backend/model/task shape before another attempt | consumes current attempt |
| `validation_failure` | implementation exists but criteria fail | generate repair attempt from failing evidence | consumes repair budget |
| `integration_conflict` | outputs collide at fan-in | route to integrator | separate integration budget |
| `loop_detected` | repeated same symptom / no-progress | trip breaker; force debugger, split, or escalation | consumes current lane and freezes identical retries |

### 9.2 Failure evidence packet
Every failure classification must persist a `FailureEvidencePacket`:
- `failure_class`
- `attempt_id`
- `task_id`
- `evidence_refs[]`
- `signature`
- `human_summary`
- `machine_action`
- `consumes_budget`
- `recommended_next_roles[]`

The next-step policy consumes this packet, not free-form text.

### 9.3 Signature-based loop detection
A loop signature is computed from:
- failing criterion ids
- normalized error excerpts
- failing command
- missing artifact pattern
- workspace inheritance basis
- recent next-action lane

If the same or near-identical signature repeats past threshold, identical retry is illegal.

---

## 10. Evidence requirements

### 10.1 Principle
No state transition that claims forward progress may rely only on worker narration.

### 10.2 Required evidence by attempt type

#### Build / repair
Must produce at least:
- diff or artifact set
- command outputs for must-pass criteria executed by Crucible or trusted deterministic executor
- workspace reference
- artifact manifest

#### Debug
Must produce at least:
- root cause note
- referenced logs/test outputs
- failing signature
- recommended next-step type

#### Review
Must produce at least:
- verdict
- criterion coverage map
- evidence sufficiency judgment
- unresolved risk list

#### Salvage
Must produce at least:
- source attempt refs
- inherited vs replayed workspace mode
- resulting artifact set
- revalidation requirements

#### Integration
Must produce at least:
- inputs consumed
- merge/conflict record
- integrated artifact manifest
- post-integration validation refs

### 10.3 Evidence sufficiency gate
A task may not move from `validated_pass` to `reviewing` or `complete` unless:
- all must-pass criterion outputs are attached
- artifact refs resolve
- winning attempt is unambiguous
- anti-vacuity check passes
- build target existence check passes where applicable

### 10.4 Rejection ledger requirement
Every rejected attempt must append:
- what was tried
- why it was rejected
- which evidence disproved it
- what kinds of next attempts are now disallowed

The rejection ledger is mandatory runtime input for the next-action selector.

---

## 11. Run / attempt / workspace model

### 11.1 Model split
v5.4 sharpens the distinction between:
- **run**: one top-level Crucible campaign
- **task**: one decomposed unit within the run
- **attempt**: one typed execution pass for a task
- **workspace**: the concrete filesystem basis used by an attempt

### 11.2 New normative contracts

#### RunRecord
Top-level lifecycle owner.

Required additions beyond v5.3:
- `run_mode: closed_loop`
- `task_closure_policy_ref`
- `chat_contract_version`
- `active_task_ids[]`
- `blocked_task_ids[]`
- `repairing_task_ids[]`

#### TaskRecord
Replaces a shallow task snapshot with closure-oriented state.

Required fields:
- `task_id`
- `role_plan`
- `status`
- `attempt_ids[]`
- `current_attempt_id`
- `winning_attempt_id`
- `failure_history[]`
- `rejection_ledger[]`
- `workspace_policy`
- `review_required`
- `integration_required`
- `budgets`

#### AttemptRecord v5.4
Extends the current `TaskAttemptRecord`.

Required new fields:
- `attempt_type`
- `parent_attempt_id`
- `derived_from_attempt_ids[]`
- `workspace_id`
- `workspace_mode`
- `failure_packet_ref`
- `result_evidence_refs[]`
- `review_verdict`
- `supersedes_attempt_id`
- `superseded_by_attempt_id`
- `next_action_chosen`

#### WorkspaceRecord
New first-class model.

Required fields:
- `workspace_id`
- `task_id`
- `basis_type: fresh | inherited | replayed | integrated`
- `basis_ref`
- `path`
- `source_attempt_ids[]`
- `mutable: bool`
- `created_at`
- `cleanup_status`

### 11.3 Workspace policy
Every task declares one of:
- `fresh_per_attempt`
- `inherit_on_salvage_only`
- `inherit_on_repair_allowed`
- `integration_only_fresh_merge`

Default for builder/repair is `fresh_per_attempt` unless the task explicitly opts into inheritance. This keeps retry behavior deterministic and reduces contamination.

### 11.4 Winning attempt semantics
Exactly one attempt per task may be `winning_attempt_id`, and only if:
- it passed must-pass validation
- any required reviewer accepted it
- any required integration succeeded

Prior attempts remain immutable and queryable.

---

## 12. Chat-surface contract

### 12.1 Principle
The chat surface is an observer and summarizer of runtime semantics, not the runtime's hidden control plane.

### 12.2 New runtime statuses exposed to chat
`status/watch` must expose task-level semantic states:
- `queued`
- `building`
- `validating`
- `repairing`
- `debugging`
- `reviewing`
- `salvaging`
- `integrating`
- `awaiting_user`
- `blocked`
- `complete`

### 12.3 Required event families
In addition to v5.3 events, v5.4 adds:
- `attempt_started`
- `attempt_superseded`
- `attempt_rejected`
- `repair_scheduled`
- `debug_scheduled`
- `salvage_scheduled`
- `review_requested`
- `review_accepted`
- `review_rejected`
- `workspace_created`
- `workspace_inherited`
- `failure_packet_created`
- `next_action_selected`
- `task_blocked`
- `task_completed`

### 12.4 Chat update contract
The embedding layer should be able to render concise updates directly from runtime state:
- start: what tasks were accepted and what Crucible is doing first
- progress: which task is building/repairing/debugging now
- blockers: exact reason and required user action
- completion: completed tasks, evidence summary, unresolved non-blockers

### 12.5 No hidden semantic invention
The chat layer must not invent states like “trying another fix” unless the runtime has emitted the corresponding `repair_scheduled` / `attempt_started` events.

---

## 13. Deterministic next-action selector

### 13.1 New subsystem
v5.4 introduces a deterministic **NextActionSelector** that consumes:
- task state
- latest attempt record
- failure evidence packet
- rejection ledger
- attempt budgets
- workspace policy
- role handoff rules

and produces one of:
- `complete_task`
- `schedule_review`
- `schedule_repair`
- `schedule_debug`
- `schedule_salvage`
- `schedule_integration`
- `ask_user`
- `block_task`
- `split_task`
- `revise_plan`

### 13.2 Deterministic inputs only
The selector may not inspect raw chat history. It works from persisted runtime state only.

### 13.3 Decision transparency
Every decision must be persisted as:
- inputs considered
- rule fired
- action selected
- rejected alternatives

This is required for auditability and future tuning.

---

## 14. Orchestrator changes required for v5.4

### 14.1 Orchestrator role shift
The current `Orchestrator.run_build()` is phase-oriented. In v5.4, the orchestrator becomes a **task-closure driver**.

Its responsibilities expand to:
- maintain per-task closure loops
- schedule role-specific attempt types
- apply failure-class-driven next actions
- request reviewer/debugger/salvage lanes deterministically
- enforce workspace policy and winner selection
- treat validation as an iterative control point, not a terminal pass/fail epilogue

### 14.2 New orchestrator phases
Recommended v5.4 top-level phases:
- `intake`
- `ambiguity`
- `decompose`
- `dispatch_initial`
- `closed_loop_execution`
- `integration`
- `final_validation`
- `done`
- `blocked`

The important change is that most task work happens inside `closed_loop_execution`, not in a single execute→validate sweep.

### 14.3 Honest executor becomes an attempt executor
`run_executor.py` should evolve from “execute all criteria honestly” into “execute one typed attempt honestly and return structured evidence.”

Recommended split:
- `attempt_executor.py` — executes one build/repair/debug/revalidate/integrate attempt
- `validation_executor.py` — runs deterministic criteria and evidence checks
- `task_closure_driver.py` — loops attempts until terminal task verdict

This preserves the honesty improvement while making room for closed-loop behavior.

---

## 15. OpenClaw tool/runtime changes required for v5.4

### 15.1 Tool contract evolution
`openclaw_tool.py` remains the embedding surface, but its job changes from “invoke Crucible commands” to “surface a richer runtime state machine.”

New required outputs:
- task semantic states
- current attempt ids/types
- blocked task reasons
- reviewer/debugger/salvage activity
- recommended user action packet when awaiting clarification/dependency

### 15.2 Detach/watch/status semantics
For long-running mobile UX, `watch` and `status` must make the closed loop obvious. For each active task they should answer:
- what was the latest failed attempt?
- what next action did Crucible choose?
- what role is active now?
- is Crucible waiting on the user or still progressing autonomously?

### 15.3 Skill-layer simplification
A major v5.4 goal is that the skill no longer needs to invent repair strategy after a run starts. The skill should:
- create or submit the initial structured plan
- invoke Crucible
- monitor Crucible events
- relay blockers or summaries

It should not have to manually author “repair prompt v2” in the ordinary path.

---

## 16. Migration from v5.3

### 16.1 What v5.4 preserves
v5.4 keeps these v5.3 wins:
- durable run store
- resumability
- preflight linting
- honest execution of verification commands
- machine-readable CLI/tool surface
- adapter abstraction
- append-only event log

### 16.2 What changes
v5.4 changes the meaning of a run from:
- “execute the submitted task plan and report outcomes”

to:
- “drive each task to deterministic closure using runtime-owned attempt policies.”

### 16.3 Migration path

#### Phase A: introduce attempt types without behavior change
- extend `TaskAttemptRecord`
- add `attempt_type`, `workspace_id`, `failure_packet_ref`, `next_action_chosen`
- keep current single-pass executor behavior

#### Phase B: add failure evidence packets + next-action selector
- persist normalized failure packets
- implement deterministic selector
- emit next-action events even if still single-step initially

#### Phase C: move from task-pass/task-fail to task-closure loops
- wrap current executor in per-task loop
- support repair/debug/review attempt routing
- enforce non-identical retry rule

#### Phase D: add workspace records and salvage policy
- formalize inheritance modes
- support salvage attempts and winner lineage

#### Phase E: upgrade chat/tool contract
- expose semantic task states and blocker packets
- reduce skill-side repair orchestration

#### Phase F: retire v5.3’s “outer continuation owns repair” assumption
- documentation update
- templates update
- E2E tests centered on closed-loop repair behavior

### 16.4 Compatibility rule
Existing v5.3 plans remain valid as initial intake, but if they omit v5.4-specific fields, Crucible applies defaults:
- review required for non-trivial code tasks
- fresh workspace per attempt
- one builder lane first
- repair routed from validation failure
- debugger routed after repeated non-identical failure

---

## 17. Validation matrix for v5.4

### 17.1 Required runtime behaviors
- Crucible autonomously performs at least one build → fail → repair → retest loop without outer LLM continuation
- repeated identical failure signatures trip a breaker and force a different lane
- reviewer rejection routes deterministically to repair/debug
- partial attempt artifacts are salvageable through an explicit policy path
- task status remains queryable throughout detached execution and resume
- workspace lineage is preserved across attempts

### 17.2 Required E2E scenarios
1. **Simple repair loop**  
   Initial build fails test; Crucible schedules repair; repair passes; reviewer accepts.

2. **Debugger handoff**  
   Two non-identical repairs still fail same criterion; Crucible routes to debugger; debugger recommends architecture or targeted repair.

3. **Partial salvage**  
   Attempt times out after producing useful diff/artifacts; Crucible schedules salvage; salvage completes and revalidates.

4. **Environment block**  
   Verification fails because dependency/tooling missing; Crucible classifies environment block and does not burn repair budget.

5. **Ambiguity escalation**  
   Runtime reaches a decision boundary requiring user input and emits a precise blocker packet.

6. **Integration repair**  
   Parallel outputs integrate with conflict or post-integration failure; Crucible routes to integrator then merged-output repair.

7. **Resume mid-repair**  
   Host dies during repair loop; `resume` reconstructs active task state and continues without semantic drift.

### 17.3 Blocking acceptance criteria
v5.4 is not complete unless:
- the runtime, not the skill, chooses normal repair/debug/salvage next steps
- attempt lineage is durable and inspectable
- evidence requirements are enforced at every acceptance gate
- the chat surface can faithfully report semantic progress from runtime state alone

---

## 18. Non-goals for v5.4

v5.4 does not attempt to:
- move natural-language planning into Crucible
- eliminate LLM workers from build/debug/review tasks
- solve cloud deployment orchestration
- replace the adapter abstraction with fully async-native backends yet
- guarantee perfect autonomous completion on every architecture-level request

The goal is narrower and more important:
- make the long-running software execution loop **Crucible-owned, deterministic where it should be, and evidence-gated end to end**.

---

## 19. Summary of anchor decisions

v5.4 makes these anchor decisions:
- Crucible owns task closure, not just task verification
- retries become typed attempts: build, repair, debug, review, salvage, integrate, revalidate
- failure taxonomy now drives deterministic next actions through persisted failure packets
- builder/reviewer/debugger/salvage handoffs are explicit runtime policy
- workspaces become first-class state with deterministic inheritance rules
- evidence gates every completion-relevant transition
- chat observes runtime semantics instead of inventing repair narrative
- v5.3 durability and honesty are preserved, but the repair loop moves inside the harness

That is the v5.4 spec.
