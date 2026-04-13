# Crucible Specification v7: Execution-Core-First Software Factory

**Status:** Draft for review  
**Date:** 2026-04-09  
**Supersedes:** `docs/crucible-spec-v6.1.md` where they conflict  
**Read first with this doc:**
- `docs/crucible-spec-v6.1.md` — thin control plane + recovery model
- `docs/crucible-spec-v5.4.md` — closed-loop executor + failure taxonomy
- `docs/agentic-harness-spec-v5.2.md` — implemented runtime/control-plane foundation
- `/Users/millieclaw/.openclaw/workspace/docs/agentic-toolkit-architecture-v4.6.2.md` — original end-state vision
- `docs/evals/swebench-verified/v6.1-batch-report.md` — the evidence that motivated v7
- `src/crucible/runtime/run_executor.py` — current executor gap
- `src/crucible/runtime/local_shell_adapter.py` — current backend gap

---

## 1. Why v7 exists

v5.2 through v6.1 built a substantial amount of real infrastructure:
- append-only state and evidence
- durable run storage
- retry and blocker policy
- control-plane recovery behavior
- thin failure-class semantics
- validation persistence
- honest run termination

That work was necessary.

But two things are simultaneously true:

1. **The current Crucible runtime is still not a true software-solving engine in the shipped CLI path.**
   SWE-bench showed that the loop is often managing repeated verification rather than driving code change.

2. **A large portion of the originally intended workflow from v4.6.2 was never actually implemented.**
   The original vision included:
   - mandatory plan-first execution
   - typed reviewer policies
   - rejection ledger
   - bug-fix protocol
   - graded contract validation
   - audit-grade prompt and evidence logging
   - tiered context loading
   - explicit build-loop artifacts

So v7 exists for two reasons:
- make the **execution core** first-class
- restore the **missing workflow architecture** that was envisioned in v4.6.2 but not yet built

This document is therefore not just “v6.1 plus a better worker.”
It is a unification of:
- the best implemented control-plane/runtime ideas from v5.2-v6.1
- the unimplemented but still correct software-factory workflow from v4.6.2

---

## 2. The product promise of v7

Crucible v7 should make the following user interaction real:

> The user says: “Use Crucible to build this.”
>
> Crucible then:
> - understands the task
> - resolves ambiguity
> - writes a real plan
> - decomposes the work
> - executes the implementation loop
> - runs the right validation and review policies
> - persists the full audit trail
> - continues until success or a real blocker
>
> and the user can inspect the entire loop on disk afterward.

That means Crucible is not just:
- a verifier
- a retry engine
- a shell adapter
- a run log

It is a **software factory runtime** with:
- execution intelligence
- policy governance
- validation truthfulness
- full observability

---

## 3. The central architecture distinction

Crucible has three major layers.

### 3.1 Execution core

The execution core owns the software work itself.

It is responsible for:
- understanding the task/spec/bug
- inspecting the repository
- identifying relevant files and contracts
- producing a plan before implementation
- selecting the next software change strategy
- editing code or task-relevant environment state
- interpreting failures
- revising the plan and hypothesis
- responding to reviewer and validator findings

It answers:

> “What should be changed next to move the software task toward completion?”

### 3.2 Control plane

The control plane owns loop policy and truthfulness.

It is responsible for:
- budgets
- attempt typing
- repeated-failure detection
- circuit breaking
- blocker semantics
- run state
- durable eventing
- escalation policy
- deciding continue / pause / stop / reroute

It answers:

> “Should the loop continue, change shape, escalate, or stop?”

### 3.3 Validation and audit layer

The validation/audit layer independently checks whether claimed progress is real and preserves the full trail.

It is responsible for:
- verification commands
- validation ladder enforcement
- reviewer execution
- prompt / response capture
- artifact manifests
- dated and timestamped audit logs
- reproducible on-disk history

It answers:

> “What evidence proves the claim, and can a human inspect the full chain afterward?”

---

## 4. The v7 design rule

The boundary for v7 is:
- **execution core owns software strategy and plan revision**
- **control plane owns loop policy and budgets**
- **validation/audit owns proof and observability**

No layer should silently absorb the job of another.

Specifically:
- the execution core must not invent final completion on its own
- the control plane must not try to hand-script every software tactic
- the validation layer must not defer truth to model prose

---

## 5. The main diagnosis from v6.1 and SWE-bench

The current CLI/runtime path has a structural gap:
- a criterion verification command is too often passed through as the worker prompt
- the default backend executes that prompt directly
- the control plane correctly escalates repeated failures
- but the underlying software-solving content loop never really starts

That means the current system can often do:
- honest failure persistence
- durable retries
- budget exhaustion
- classification

But it still often cannot do:
- task-aware planning
- repo-aware implementation
- code-edit / test / revise closure
- reviewer-aware repair
- environment repair as software work

v7 is explicitly designed to close this gap.

---

## 6. Non-negotiable starting flow

This is mandatory in v7.

Whenever a user invokes Crucible for a software task, the loop begins as:

```text
intake
→ ambiguity check
→ context loading
→ plan creation
→ plan validation
→ task decomposition
→ build execution
→ validation
→ review
→ repair / iterate / integrate / ship
```

### 6.1 Plan-first mandate

No matter how large or small the task is, the first software step is:
1. understand context
2. produce a plan
3. define validation and reviewer policy
4. only then begin building

This rule applies to:
- bug fixes
- one-file changes
- large greenfield builds
- existing-project iteration

The plan can be small for a small task, but it is never skipped.

### 6.2 What the plan must include

Every plan must declare:
- what is being built
- how it will be validated
- what reviewer types will run
- which gates are must-pass
- what failure looks like
- whether the task is bug-fix vs implementation vs integration vs refactor
- what context is HOT, WARM, and COLD

---

## 7. OpenClaw invocation model

Crucible must support a chat-native invocation flow.

### 7.1 User-facing entry

The default invocation shape is:

> “Use Crucible to build this …”

This should route into the Crucible skill / tool entrypoint and create a full Crucible run rather than a generic one-off coding turn.

### 7.2 Required OpenClaw flow

The OpenClaw wrapper should:
1. capture the user task
2. create a Crucible run record
3. run ambiguity + planning first
4. persist the plan and run state
5. use Crucible-controlled execution semantics for the remainder

The user should not need to know internal commands.
The system should behave like a first-class chat capability.

---

## 8. High-level architecture

```text
User / Chat Surface
        │
        ▼
OpenClaw Crucible Skill / Tool Entry
        │
        ▼
Intake + Ambiguity Gate
        │
        ▼
Plan System
- plan creation
- validation policy
- reviewer policy
- decomposition
        │
        ▼
Control Plane
- budgets
- attempt roles
- state machine
- circuit breaker
- escalation logic
        │
        ▼
Execution Core
- repo inspection
- strategy memory
- code edits
- environment repair
- failure interpretation
        │
        ▼
Validation + Review + Audit
- contract validation ladder
- reviewer lanes
- prompt / response logs
- evidence artifacts
        │
        ▼
Integration / Ship / Learn
```

---

## 9. New first-class subsystems in v7

v7 requires the following conceptual subsystems to exist clearly, even if some reuse existing code:

```text
src/crucible/
├── execution_core/
├── planning/
├── review/
├── audit/
├── contracts/
├── failures/
├── state/
├── runtime/
└── openclaw/
```

### 9.1 `planning/`

Owns:
- ambiguity detection
- plan generation
- plan validation
- decomposition
- reviewer and validation policy declaration

### 9.2 `execution_core/`

Owns:
- execution packet construction
- repo inspection
- strategy memory
- worker prompt generation
- patch/result normalization
- failure feedback shaping

### 9.3 `review/`

Owns:
- reviewer personas
- review tiers
- review input shaping
- review finding normalization
- rejection ledger production

### 9.4 `audit/`

Owns:
- prompt logs
- completion logs
- event logs
- artifact manifests
- dated on-disk run history

### 9.5 `contracts/`

Owns:
- contract validation ladder
- must-pass vs informational gate semantics
- anti-vacuity enforcement
- mutation-testing hooks when available

---

## 10. Plan system

The planning system is mandatory and comes before build execution.

### 10.1 Inputs

Plan creation consumes:
- user request
- repo/workspace target
- ambiguity results
- relevant project knowledge
- prior run history if resuming
- risk tier inputs

### 10.2 Outputs

The plan system produces a durable plan artifact containing:
- feature/problem statement
- success criteria
- decomposition into tasks
- verification triples per task
- review policy per task
- contract validation policy
- task type classification
- risk tier
- budget policy
- integration and ship criteria

### 10.3 Plan validation

A plan is invalid if it has any of:
- no measurable verification path
- missing success criteria
- ambiguous scope boundaries
- undefined deliverables
- missing reviewer policy
- missing validation policy
- cyclical task dependencies

### 10.4 Plan-first hard gate

No execution packet may be created until the plan artifact exists and passes plan validation.

---

## 11. Task decomposition and verification triple

Each task must define a verification triple:
- **what to build**
- **how to verify it**
- **what failure looks like**

This remains mandatory from prior versions.

### 11.1 Additional v7 requirement

Each task must also declare:
- `task_type`: implementation | bug_fix | integration | refactor | docs | security_hardening
- `review_policy`: what reviewer lanes must run
- `validation_policy`: what contract validation levels must run
- `must_pass_gates`
- `informational_gates`

---

## 12. Execution packet

The central v7 worker interface is the `ExecutionPacket`.

### 12.1 Purpose

A worker/backend must receive enough information to solve a software task, not merely repeat a command.

### 12.2 Required fields

An execution packet should include at minimum:
- `task_goal`
- `task_type`
- `problem_statement`
- `success_criteria`
- `repo_summary`
- `relevant_files`
- `hot_context`
- `warm_context_refs`
- `environment_summary`
- `attempt_type`
- `attempt_number`
- `plan_excerpt`
- `verification_targets`
- `must_pass_gates`
- `review_policy`
- `validation_policy`
- `prior_attempt_summary`
- `rejection_ledger`
- `strategy_memory`
- `current_hypothesis`
- `prompt_constraints`

### 12.3 Explicit rule

`verification_command` is validation input, not the primary worker prompt.

---

## 13. Tiered context model

The v4.6.2 context model is restored in v7.

### 13.1 HOT

Always injected:
- current task definition
- exact spec section
- files already known to be relevant
- current failure evidence
- rejection ledger
- current hypothesis

### 13.2 WARM

Available by reference / fetch:
- nearby modules
- related test files
- project knowledge file
- recent lessons
- adjacent architecture files

### 13.3 COLD

Searchable but not bulk-loaded:
- full project history
- old specs
- archived runs
- deep transcript memory
- historical lessons across projects

### 13.4 Rule

The execution core must deliberately manage context tiering rather than naïvely loading everything.

---

## 14. Three-pass task loop

v7 restores the originally intended three-pass per-task loop.

### 14.1 Pass 1: Build

Goal:
- produce or revise the implementation itself

Consumes:
- plan
- execution packet
- current repo state
- prior rejections / findings

Produces:
- code changes
- test additions or updates
- structured builder result
- patch summary

### 14.2 Pass 2: Contract validation

Goal:
- run the strongest practical validation ladder for the task

Consumes:
- produced artifacts / code state

Produces:
- validation report
- must-pass and informational gate results
- anti-vacuity status
- mutation status when available

### 14.3 Pass 3: Post-build review

Goal:
- independently assess whether the change actually satisfies the spec and risk profile

Consumes:
- spec
- diff
- validation output
- artifacts

Produces:
- reviewer report(s)
- rejection ledger updates if rejected
- verdict

### 14.4 Loop behavior

A failure in pass 2 or 3 routes back to pass 1 with structured evidence.

---

## 15. Bug-fix protocol

Bug-fix tasks are a first-class task type in v7.

### 15.1 Mandatory flow

Every bug-fix task must follow:
1. investigate
2. reproduce
3. fix
4. verify

### 15.2 Investigate

The execution core must first trace actual behavior and form a hypothesis from evidence.

### 15.3 Reproduce

A reproducing test or deterministic reproduction step must exist and must fail before the fix.

### 15.4 Fix

The fix should be applied after the reproduction exists.

### 15.5 Verify

The reproducing test must pass after the fix, and regression checks must run.

### 15.6 Structured bug-fix state

Task state should capture:
- `reproduce_test_written`
- `reproduce_failed_before_fix`
- `reproduce_passed_after_fix`
- `investigation_summary`

### 15.7 Three-strike rule

If three fix attempts fail without changing the underlying failure meaningfully, the system must treat the current mental model as wrong and re-enter investigation rather than blindly continue.

---

## 16. Reviewer system

v7 restores reviewer typing and policy.

### 16.1 Reviewer isolation rule

Reviewers must not see builder reasoning or chain-of-thought style summaries.
They receive:
- spec
- diff
- validation outputs
- artifacts
- explicit review assignment

### 16.2 Reviewer tiers

#### Tier 0
- deterministic audit only
- no model reviewer required

#### Tier 1
- spec compliance reviewer
- must produce:
  - criterion-by-criterion assessment
  - one likely escaped defect
  - one untested path
  - verdict

#### Tier 2
- tier 1 reviewer
- plus adversarial security reviewer
- applies OWASP + STRIDE style review

#### Tier 3
- tier 2 reviewers
- plus explicit human checkpoint for shipping/publishing when configured

### 16.3 Reviewer personas

Reviewer types include at minimum:
- spec compliance reviewer
- adversarial reviewer
- security reviewer
- integration reviewer
- regression reviewer
- architecture reviewer

Not every task needs all reviewer types, but the plan must specify the policy.

### 16.4 Cross-model rule

When possible, the reviewer model should differ from the builder model.
This is a policy preference because shared-model blind spots are real.

### 16.5 Reviewer findings schema

Each reviewer report should include:
- covered criteria
- unmet criteria
- likely escaped defect
- untested path
- evidence gaps
- residual risk
- verdict
- confidence

---

## 17. Security review

Security review is first-class for the appropriate tiers.

### 17.1 Trigger conditions

Security review becomes required when:
- auth / credential / secret handling is touched
- permission boundaries change
- external input surfaces expand
- security-sensitive keywords or files are involved
- risk tier requires it

### 17.2 Review method

Security review should classify findings under frameworks like:
- OWASP Top 10
- STRIDE

### 17.3 Blocking threshold

The plan or policy should declare what severity levels block task completion or shipping.

---

## 18. Deterministic audit checklist

In addition to model reviewers, v7 requires deterministic audit checks.

Examples:
- public API changed → docs updated?
- new dependency added → justification recorded?
- migration needed → migration artifact exists?
- rollback path defined where required?
- no secrets in diff/logs?
- files touched within allowed scope or split triggered?
- bug fix has reproduce evidence?
- spec criteria each tied to evidence?

These checks should run as code where possible, not only as prose.

---

## 19. Rejection ledger

The rejection ledger is restored as a first-class runtime input.

### 19.1 Purpose

It prevents the system from retrying known-bad approaches without new evidence.

### 19.2 Required record shape

Each rejection should capture:
- attempt number
- attempted approach / patch summary
- files touched
- failure type
- validator / reviewer output
- why rejected
- what evidence invalidated it
- what lesson should constrain the next attempt

### 19.3 Runtime use

The rejection ledger must be injected into later execution packets and also considered by the next-action selector.

### 19.4 Distinction from generic event log

An append-only event ledger is not enough.
The rejection ledger is a semantic memory of failed strategies.

---

## 20. Failure taxonomy and budget semantics

The v5.2/v4.6.2 failure taxonomy is retained and strengthened.

### 20.1 Core classes

At minimum:
- `ambiguity_block`
- `environment_block`
- `missing_dependency`
- `architecture_mismatch`
- `model_limitation`
- `validation_failure`
- `integration_conflict`
- `loop_detected`

### 20.2 Required next actions

Each failure class maps to a distinct next-action policy, not generic retry.

### 20.3 Budget semantics

Environment and missing-dependency failures should not consume ordinary implementation retry budget.

### 20.4 Validation failure semantics

Validation failure should route to repair with the exact failing evidence as structured input.

---

## 21. Circuit breaker

The circuit breaker must be stronger than simple retry counts.

### 21.1 Independent signals

The loop should trip when any configured threshold is met for:
- repeated same-error signature
- repeated no-progress iterations
- repeated low-value / clearly looping output

### 21.2 Post-breaker policy

After a breaker trips, the next step must be non-identical to the failed trajectory.
For example:
- split the task smaller
- change reviewer/backend/model
- re-enter investigation
- switch builder to debugger mode
- escalate on ambiguity or architecture issues

---

## 22. Contract validation ladder

v7 restores explicit graded contract validation.

### 22.1 Validation philosophy

The system should run the strongest practical validation available and tie it back to the spec.

### 22.2 Validation levels

v7 should support an explicit validation ladder such as:
- static checks
- targeted tests
- local build/run checks
- proof/demo artifacts
- CI validation
- optionally stronger environment-specific levels where available

### 22.3 Per-project declaration

Projects should be able to declare available validation levels and concrete commands.

### 22.4 Must-pass vs informational

Each task declares:
- must-pass validation gates
- informational gates

### 22.5 Anti-vacuity

A task cannot be considered complete if validation would still pass after removing or clearly breaking the claimed implementation.

### 22.6 Mutation testing

Where practical, mutation-style checks should be available as a stronger form of anti-vacuity evidence.

---

## 23. Prompt and completion audit logs

This is mandatory in v7.

### 23.1 Requirement

For every task and attempt, the system must store on disk:
- exact prompt sent to the model/worker
- exact model response / structured result
- timestamp
- model/backend identity
- attempt type
- related artifacts

### 23.2 User expectation

The user must be able to inspect the full loop afterward, including what the LLM was told and what it returned.

### 23.3 Run layout

Each run should maintain a dated and timestamped directory containing at minimum:
- run metadata
- events log
- prompt logs
- response logs
- evidence manifests
- validation outputs
- reviewer outputs
- final result summary

### 23.4 Privacy / safety note

Audit storage may support redaction policies for secrets, but not at the expense of losing the ability to reconstruct the software loop.

---

## 24. Durable artifact chain

Every phase should explicitly name what it produces and what the next phase consumes.

### 24.1 Core artifacts

At minimum:
- `plan.json` or equivalent durable plan artifact
- `execution_packet.json`
- builder result artifacts
- validation report artifacts
- reviewer report artifacts
- rejection ledger artifact
- integration artifact
- final run summary

### 24.2 Rule

No phase should depend on a prose summary that is not persisted as an artifact.

---

## 25. State model

The v7 state model must combine the runtime durability of v5.2+ with the richer workflow semantics from v4.6.2.

### 25.1 Build-level state

Must include at least:
- build/run id
- phase
- created/updated timestamps
- spec path
- repo/workspace target
- branch/workspace lineage
- risk tier
- token/cost budgets
- task list
- current task index
- append-only events

### 25.2 Task-level state

Must include at least:
- task id
- task type
- verification triple
- reviewer policy
- validation policy
- current pass (`plan | build | contract | review | integrate | done | failed`)
- build/contract/review attempt counts
- rejection ledger entries
- breaker counters
- last error signature
- bug-fix sub-state where relevant

### 25.3 Pass result shape

Each pass result should capture:
- status
- timestamp
- duration
- output refs
- error signature
- cost/token usage where known

---

## 26. Cost and risk policy

### 26.1 Risk tiers

Tasks and builds should be assigned deterministic risk tiers based on:
- touched files
- lines changed
- security-sensitive keywords
- feature class

### 26.2 Token and cost budgets

Plans should define token and/or cost budgets per run/build, with warning thresholds and hard stops.

### 26.3 Model routing

The chosen model/backend should be policy-aware:
- stronger models for harder implementation and security review
- different model for review where possible
- cheaper models where appropriate for light work

---

## 27. Parallelism and work isolation

### 27.1 Default stance

Parallelism is not the default. It should be deliberate.

### 27.2 Parallel-safe conditions

Parallel execution is allowed only when:
- file overlap is low or isolated
- validation commands are separable
- integration plan is explicit

### 27.3 Isolation

Each worker should operate in an isolated workspace/worktree when concurrency could cause contamination.

---

## 28. Sandbox-before-apply

v7 keeps the rule that changes should be validated in an isolated workspace before being considered integrated into the main target branch/state.

---

## 29. Flaky test protocol

The system should distinguish:
- deterministic failure
- flaky failure
- unavailable validation

Flaky tests should be tracked explicitly rather than folded into generic validation noise.

---

## 30. Ship checklist

The ship step should be a real gate, not a hand-wave.

At minimum it should verify:
- integration complete
- full required validation complete
- docs updated if required
- no unresolved blocking reviewer/security findings
- secrets audit clean
- spec criteria each tied to evidence
- CI state acceptable where configured

---

## 31. Learn phase

v7 restores a post-build learn/update phase.

### 31.1 Outputs

A completed run should be able to update:
- per-project lessons
- knowledge files
- cost logs
- daily memory / durable operational notes

### 31.2 Purpose

The system should not only finish work; it should improve future work.

---

## 32. What is already built vs required by v7

### 32.1 Already substantially present in current code

The current codebase already contains meaningful pieces of:
- append-only run/event persistence
- validation persistence
- anti-vacuity logic
- validation ladder semantics
- reviewer input isolation
- failure selector / control-plane logic
- durable run directories

### 32.2 Required but still missing or incomplete

v7 explicitly requires first-class implementations for:
- plan-first execution as a gate
- execution packet builder
- real code-editing default path
- typed reviewer policies
- rejection ledger as semantic runtime memory
- prompt/response audit logs
- bug-fix task type protocol
- tiered context management
- learn/lesson persistence integration
- stronger cost/risk policy

v7 is successful only if these become runtime reality, not just spec text.

---

## 33. Suggested implementation phases

### Phase 1: Plan system + execution packet foundation
Build:
- ambiguity gate
- plan artifact
- plan validation
- decomposition metadata
- execution packet model

### Phase 2: Restore workflow semantics
Build:
- three-pass task loop
- task types
- bug-fix protocol state
- reviewer policy declaration
- must-pass/informational gate policy

### Phase 3: Review + rejection system
Build:
- reviewer personas and tiers
- security/adversarial review lanes
- rejection ledger artifact + runtime injection
- cross-model review policy hooks

### Phase 4: Audit layer
Build:
- exact prompt logs
- exact completion logs
- dated on-disk audit trail
- artifact chain manifests

### Phase 5: Execution-core closure
Build:
- repo-aware worker path as default
- real code-editing backend in shipped path
- strategy memory + feedback shaping
- non-hollow retries

### Phase 6: Learn + operational integration
Build:
- lesson persistence
- risk/cost budget enforcement
- OpenClaw first-class invocation polish
- ship checklist + learn phase

---

## 34. Success criteria for v7

v7 is only successful if all of the following are true:

1. **Plan-first is real.**
   Every task begins with context understanding and a durable plan.

2. **Execution core is real.**
   The shipped runtime can actually attempt software work, not just re-run verification commands.

3. **Typed reviews are real.**
   Reviewer policy includes deterministic audit and reviewer personas, including security review where required.

4. **Rejection memory is real.**
   Failed approaches are carried forward semantically, not merely as generic events.

5. **Auditability is real.**
   A human can inspect the full run on disk, including prompts and responses.

6. **Bug-fix discipline is real.**
   Bug-fix tasks require reproduce → fix → verify.

7. **Validation truthfulness is real.**
   Tasks cannot pass on vibes; they must pass required gates.

8. **The OpenClaw invocation is real.**
   “Use Crucible to build this” launches the real loop, not a fake wrapper.

9. **SWE-bench-style evaluation fails honestly for hard problems, not because the runtime never actually tried to solve them.**

---

## 35. The blunt summary

v5.2-v6.1 built much of the control plane and durable runtime substrate.
That was real progress.

But the original v4.6.2 vision also required:
- plan-first execution
- typed review policy
- rejection memory
- bug-fix discipline
- explicit auditability
- stronger validation contracts
- a true software-solving inner loop

v7 is the spec that reunifies those pieces.

Its architecture is simple to describe:

- **Planning layer:** understand, clarify, plan, decompose
- **Execution core:** do the software work
- **Control plane:** govern the loop honestly
- **Validation/review/audit:** prove the work and preserve the record

That is the shape Crucible needs if it is going to become the software factory originally envisioned, rather than remaining a strong but incomplete runtime shell.
