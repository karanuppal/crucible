# Crucible Specification v7: Execution-Core-First Software Factory

**Status:** Draft for review  
**Date:** 2026-04-09  
**Supersedes:** `docs/crucible-spec-v6.1.md` where they conflict  
**Read first with this doc:**
- `docs/crucible-spec-v6.1.md` — thin control plane + recovery model (v7 preserves this)
- `docs/crucible-spec-v5.4.md` — closed-loop executor + failure taxonomy
- `docs/architecture.md` — current subsystem map
- `docs/evals/swebench-verified/v6.1-batch-report.md` — the evidence that motivated v7
- `src/crucible/runtime/run_executor.py` — current executor (shows the gap)
- `src/crucible/runtime/local_shell_adapter.py` — current backend (shows why retries are hollow)

---

## 1. Why v7 exists

v5.3 through v6.1 made Crucible much better at the **control plane**:
- durable run state
- honest status
- evidence persistence
- retry budgets
- loop control
- blocker handling
- repeated-failure detection

That work was real and necessary.

But the latest SWE-bench runs exposed the central remaining gap:

> Crucible can now manage a loop better than it can solve the software problem inside the loop.

In the current shipped CLI/runtime path:
- the runtime often passes `verification_command` through as the worker prompt
- the default backend executes that command directly
- retries change labels (`build` → `repair` → `debug`) without materially changing the software work being done

So the control plane runs, but the software-solving loop does not.

That means v6.1 is still structurally imbalanced:
- **strong control plane**
- **weak execution core**

**v7 exists to correct that imbalance.**

The goal of v7 is not “more loop governance.”
The goal is to make Crucible’s original promise real:

> Give Crucible a software task and it should drive:  
> **understand task → inspect repo → plan → edit → test → interpret failure → revise → review → retest**  
> until success or a real blocker.

---

## 2. The central architecture distinction

Crucible has two major layers.

### 2.1 Execution core

The execution core is the thing that actually tries to solve the software problem.

Its job is to:
- read the task, bug, or spec
- inspect the repository
- identify relevant files
- form a working hypothesis
- make code changes
- run tests/validation
- interpret failures
- revise the implementation
- ask for review
- continue until done or genuinely blocked

This is the **content engine**.
It answers:

> “What should we change next to make the software task succeed?”

### 2.2 Control plane

The control plane manages the loop around that work.

Its job is to:
- decide whether to continue, pause, stop, or escalate
- classify failure at the policy level
- track budgets and repeated failures
- preserve evidence and state
- decide which attempt role comes next
- determine whether user input is required
- expose truthful runtime status

This is the **shape / policy / bookkeeping layer**.
It answers:

> “Should we keep going, force a different strategy, pause for input, or stop?”

### 2.3 The v7 design rule

The core v7 boundary is:

- the **execution core owns software work selection and adaptation**
- the **control plane owns loop policy and truthfulness**

Neither should do the other’s job.

The control plane should not try to script every repair tactic.
The execution core should not be allowed to silently invent loop policy.

---

## 3. The main diagnosis from SWE-bench

The current runtime failed for a simple reason:

### What should have happened

1. Crucible receives a real software problem.
2. The worker gets:
   - problem statement
   - repository context
   - failing tests
   - prior attempt history
   - constraints and success criteria
3. The worker edits code or environment.
4. Crucible runs validation.
5. Failure evidence goes back into the next attempt.
6. The cycle repeats.

### What actually happened

1. Crucible had the task.
2. The runtime fed `verification_command` into the worker/backend.
3. The backend ran that command directly.
4. The environment failed or the test failed.
5. The loop repeated around the same failing command.

So the current system demonstrated:
- loop control
- evidence capture
- budget exhaustion
- repeated-failure escalation

But it did **not** demonstrate:
- task understanding
- repo-aware debugging
- code editing toward a goal
- environment repair as part of solving the task
- iterative implementation

That is the architectural gap v7 is explicitly designed to close.

---

## 4. One-line summary of v7

> **v7 makes the execution core first-class.**

The worker must no longer be a thin shell command runner.
It must become a task-aware software worker operating inside a deterministic runtime.

In v7:
- the control plane remains thin, durable, and deterministic
- the execution core becomes a real software-solving loop
- validation remains runtime-owned
- review remains a real gate
- evidence remains first-class

---

## 5. Product goal

The product goal of v7 is:

> Crucible should function as a software factory runtime, not just a verification harness.

That means a run is successful only if Crucible can do the following end-to-end:
- ingest a software task
- establish a usable environment
- inspect the codebase
- choose and revise implementation strategy
- modify code or task-relevant environment state
- verify against explicit criteria
- recover from failures without losing context
- stop only at a real terminal condition

This is different from “can it run commands honestly?”
That was necessary for v5.3.
It is not sufficient for v7.

---

## 6. Architectural principles for v7

### 6.1 Execution-core-first

The execution core is now a primary subsystem, not an incidental adapter detail.

### 6.2 Control plane stays thin

The control plane should remain coarse and legible.
It exists to govern the loop, not to encode a giant ontology of software fixing strategies.

### 6.3 Runtime validation remains runtime-owned

The worker can propose and implement.
The runtime must still verify outcomes independently.

### 6.4 Full-context attempts

Every build/repair/debug attempt must be given enough context to actually solve the task.
A verification command alone is not enough.

### 6.5 Evidence-rich iteration

Each attempt must produce evidence that can shape the next attempt:
- files changed
- commands run
- test outcomes
- observed failures
- hypothesis summary
- why the next strategy differs

### 6.6 Distinguish “strategy” from “policy”

- **Policy** is runtime-owned: continue / pause / stop / escalate
- **Strategy** is execution-core-owned: what code or environment change to try next

### 6.7 Environment is part of execution, not a side precondition

Environment setup is not a one-time preflight box to check.
It is part of the software-solving loop.
If the environment is broken, fixing it may be part of solving the task.

---

## 7. The new high-level architecture

```text
User / Chat Surface
        │
        ▼
Intake + Task Shaping
- user request
- task definition
- success criteria
- repo/workspace target
        │
        ▼
Crucible Control Plane
- run state
- attempt roles
- budgets
- blocker policy
- repeated-failure detection
- durable evidence
- review gating
        │
        ▼
Crucible Execution Core
- task understanding
- repo inspection
- planning
- code editing
- environment repair
- test execution requests
- failure interpretation
- strategy revision
        │
        ▼
Validation + Review
- independent command execution
- criterion checks
- reviewer pass/reject
        │
        ▼
Terminal Outcome
- complete
- awaiting_user
- blocked
- failed_terminal
```

The key v7 change is that the execution core is a real layer with its own contracts.

---

## 8. New subsystem: `execution_core/`

v7 introduces a new top-level subsystem:

```text
src/crucible/execution_core/
├── __init__.py
├── models.py
├── context_builder.py
├── repo_inspector.py
├── task_interpreter.py
├── planner.py
├── worker_prompt.py
├── worker_session.py
├── patch_intake.py
├── strategy_memory.py
├── failure_feedback.py
└── execution_cycle.py
```

This subsystem is the missing content engine.

### 8.1 Responsibilities

The execution core is responsible for building the worker-facing software-solving context.
It should:
- transform task definition + repo state + attempt history into a solvable work packet
- preserve the evolving software hypothesis across attempts
- require explicit summaries of what was tried and why
- feed validation failures back into the next attempt
- ensure each new attempt is materially informed by prior evidence

### 8.2 Non-responsibilities

The execution core should not:
- decide final run terminal state on its own
- own budget policy
- own user blocker semantics
- mark completion without runtime validation

Those remain control-plane duties.

---

## 9. The execution packet contract

The central v7 interface is the **ExecutionPacket**.

This is what gets handed to the worker/backend for build/repair/debug work.

### 9.1 Why it exists

The current system over-relies on narrow prompts like a verification command.
That is too little information for real software work.

The worker must instead receive a structured packet containing the full software problem.

### 9.2 Required fields

An `ExecutionPacket` should include, at minimum:
- `task_goal`
- `problem_statement`
- `success_criteria`
- `regression_guardrails`
- `repo_summary`
- `relevant_files`
- `environment_summary`
- `attempt_type`
- `attempt_number`
- `prior_attempt_summary`
- `prior_failures`
- `files_previously_touched`
- `current_hypothesis`
- `strategy_directive`
- `review_requirements`
- `verification_targets`

### 9.3 Important rule

The worker should receive:
- the software problem
- the current state of the repository
- the current failure state
- what was previously tried
- how this attempt should differ

It should **not** receive only a shell command and be expected to somehow act like a software engineer.

---

## 10. Attempt semantics in v7

v6.1 was correct that attempt types are role semantics, not backend semantics.
That remains true.

Core attempt types remain:
- `build`
- `repair`
- `debug`
- `review`
- `salvage`
- `integrate`
- `revalidate`

But in v7 these attempt types must now carry richer execution expectations.

### 10.1 `build`

Goal:
- produce the first serious implementation pass for the task

The execution packet for `build` should include:
- full task/problem statement
- repo context
- implementation target
- expected validation targets

### 10.2 `repair`

Goal:
- fix a known failure after a concrete implementation attempt

The execution packet for `repair` should include:
- prior implementation summary
- exact validation failures
- files touched
- hypothesis for failure cause
- explicit instruction to revise rather than restart blindly

### 10.3 `debug`

Goal:
- recover from repeated failure, uncertainty, or collapsed search

The execution packet for `debug` should include:
- normalized repeated-failure signature
- failed strategy summaries
- requirement to produce a materially different diagnosis or plan
- optional requirement to inspect broader repo context before editing

### 10.4 `review`

Goal:
- independently test whether the proposed solution is acceptable

Review stays a gate, not narration.

### 10.5 `revalidate`

Goal:
- independently confirm claimed fixes still hold after integration or salvage operations

---

## 11. The execution cycle

The execution core itself should be iterative.

### 11.1 Canonical inner loop

```text
receive ExecutionPacket
→ inspect repo / relevant files
→ summarize working hypothesis
→ choose concrete change strategy
→ edit code or environment
→ optionally run local exploratory commands
→ emit attempt summary + artifacts
→ hand back to runtime validation
```

### 11.2 What validation then does

```text
runtime executes verification / tests / reviewer
→ builds failure evidence packet
→ control plane classifies policy state
→ if continuing, execution core builds next ExecutionPacket
```

### 11.3 Critical separation

The execution core proposes and changes.
The runtime validates and governs.

---

## 12. Environment provisioning changes in v7

v7 changes the role of environment provisioning significantly.

### 12.1 Current problem

The current environment subsystem can record a workspace as “provisioned” without proving that the target validation tool actually runs.

For example:
- `.venv` exists
- Python exists
- metadata says provisioned
- but `pytest` is missing

That is not a usable environment.

### 12.2 v7 rule: usable means runnable for the target task

An environment is only considered ready if Crucible can prove that the intended validation surface is runnable.

For Python, that may mean proving one or more of:
- target interpreter resolves
- `pytest` exists when pytest-based verification is expected
- project-specific test runner exists
- key import path is usable

### 12.3 Environment becomes execution-core-addressable

If environment setup is incomplete or wrong, the next attempt may still be `repair` or `debug`, but the execution packet may explicitly instruct the worker to:
- correct dependency installation
- choose the right setup path for the repo
- use repo-specific tooling
- verify the target command now runs

This keeps the control plane coarse while making environment recovery part of the real solving loop.

---

## 13. Control-plane model in v7

The v6.1 thin control plane remains the right direction.

Top-level policy classes remain:
- `retryable`
- `needs_user_input`
- `stuck_or_repeating`
- `terminal_nonrecoverable`

### 13.1 Why v7 does not replace this

The problem was not primarily that the control plane had the wrong classes.
The problem was that the execution core behind those classes was too weak.

So v7 keeps the thin control-plane model and strengthens what sits inside it.

### 13.2 What the control plane decides

The control plane still decides:
- whether the run remains autonomous
- whether user input is required
- whether search has collapsed
- whether to stop
- which attempt role comes next
- which budget is spent

### 13.3 What the control plane must not decide

It should not hardcode detailed implementation tactics like:
- exactly which package manager to use
- exactly which file to patch first
- exact root-cause diagnosis
- exact repair maneuver

Those are execution-core responsibilities.

---

## 14. Strategy memory

A major v7 requirement is that retries must become **substantive**, not just relabeled.

To make that real, the execution core needs a durable `StrategyMemory`.

### 14.1 What it stores

Per attempt, store:
- hypothesis summary
- change summary
- files edited
- exploratory commands run
- validation outcome
- why this strategy was chosen
- why it failed or partially succeeded

### 14.2 Why it matters

Without strategy memory, “try something different” is vague.
With it, Crucible can concretely say:
- previous attempt changed parser dispatch in `fits.py`
- failure remained in extension inference
- next debug attempt should inspect header normalization path instead of retrying dispatch edits

That is the difference between a loop and a real search process.

---

## 15. Prompting / worker contract in v7

v7 formalizes a stronger worker contract.

### 15.1 Worker inputs

A worker should receive:
- the execution packet
- repository path
- allowed tools/environment
- prior attempt summaries
- structured failure evidence
- explicit instruction to produce software progress, not commentary

### 15.2 Worker outputs

A worker should return a structured result containing:
- `summary`
- `hypothesis`
- `changes_made`
- `files_touched`
- `commands_run`
- `artifacts_produced`
- `claimed_status`
- `open_risks`
- `suggested_next_focus_if_fail`

### 15.3 Why this matters

The runtime cannot build a meaningful next attempt if the worker returns only freeform prose or raw shell output.
The worker result must feed the next cycle.

---

## 16. Review in v7

Review remains a first-class gate.

But v7 sharpens the boundary:

- the execution core may believe it fixed the task
- the runtime still requires independent validation and/or review
- reviewer rejection must produce execution-core-usable feedback, not just a pass/fail bit

That means review output should be transformed into structured evidence such as:
- missing regression coverage
- incomplete edge-case handling
- mismatch between claimed and actual behavior
- style / safety / architecture concerns

This feedback should then shape the next `repair` or `debug` packet.

---

## 17. Mapping current code into v7 buckets

### 17.1 Mostly control plane today

These components are primarily control-plane-shaped:
- `src/crucible/failures/`
- `src/crucible/policy/`
- `src/crucible/state/`
- `src/crucible/runtime/run_store.py`
- `src/crucible/runtime/status_emitter.py`
- `src/crucible/runtime/resume_handler.py`
- `src/crucible/orchestrator/task_state_machine.py`
- `src/crucible/orchestrator/run_closure.py`
- `src/crucible/runner/non_identical_rule.py`
- `src/crucible/runner/handoff_controller.py`

These are about loop semantics, policy, evidence, and durable truth.

### 17.2 Mixed / transitional today

These components currently sit at the boundary:
- `src/crucible/runtime/run_executor.py`
- `src/crucible/orchestrator/closed_loop_executor.py`
- `src/crucible/environment/existing_repo.py`
- `src/crucible/runner/role_executor.py`
- `src/crucible/runtime/openclaw_adapter.py`
- `src/crucible/runtime/local_shell_adapter.py`

These files currently mix:
- execution triggering
- validation
- adapter behavior
- partial attempt semantics

In v7 they should be split more clearly between control plane and execution core.

### 17.3 Missing or underdeveloped execution core today

What is currently weak or missing:
- task-aware execution packet construction
- repo-aware work prompting
- durable strategy memory
- explicit hypothesis tracking
- worker result normalization
- meaningful failure-to-next-attempt feedback shaping
- real code-editing backend expectations in the default runtime path

That is the heart of v7.

---

## 18. Required runtime behavior changes

### 18.1 Stop using verification commands as worker prompts

This is the most important immediate correction.

A verification command is for validation.
It is not a software task description.

### 18.2 Separate worker execution from validation execution

Worker-side exploratory or implementation commands may happen inside the execution core.
Validation commands must remain runtime-owned and evidence-backed.

### 18.3 Make every continuing attempt materially informed

If an attempt continues after failure, the next attempt must be able to answer:
- what failed
- what we think caused it
- what we already tried
- why this next attempt is different

### 18.4 Make environment readiness task-relative

Provisioning must prove readiness for the target task, not merely that a shell or interpreter exists.

### 18.5 Support real software workers in the default path

The default runtime path must be capable of:
- reading repo files
- editing code
- running exploratory commands
- returning structured attempt output

Otherwise Crucible remains a verification harness, not a software factory runtime.

---

## 19. Proposed code organization changes

### 19.1 Add execution-core modules

Add:
- `src/crucible/execution_core/`

### 19.2 Narrow runtime adapters

Adapters should become clearer about what they are:
- **software worker adapter**: accepts `ExecutionPacket`, returns structured worker result
- **validation executor**: runs verification commands independently

### 19.3 Refactor `run_executor.py`

`run_executor.py` should no longer be the place where “worker prompt = verification command” logic lives.

Instead it should:
1. request an `ExecutionPacket`
2. send it to the configured worker backend
3. persist worker result
4. run validation independently
5. build failure evidence
6. hand control decisions to the selector/state machine

### 19.4 Add `strategy_memory` persistence

This can likely live adjacent to runtime/evidence storage, but conceptually belongs to the execution core.

---

## 20. Suggested implementation phases for v7

### Phase 1: Execution packet foundation

Deliver:
- `ExecutionPacket` model
- context builder from task + repo + attempt history
- worker result schema
- stop feeding verification commands directly as worker prompts

### Phase 2: Execution-core feedback loop

Deliver:
- failure feedback shaping
- strategy memory
- explicit hypothesis capture
- materially-different retry instructions grounded in prior attempts

### Phase 3: Environment-as-execution integration

Deliver:
- stronger task-relative environment readiness checks
- ability for repair/debug attempts to address environment/tooling gaps as part of real execution
- proof that selected test tool is runnable before “provisioned” is accepted

### Phase 4: Review-feedback integration

Deliver:
- structured reviewer feedback packets
- automatic conversion of reviewer rejection into repair/debug execution context

### Phase 5: Real benchmark/runtime closure

Deliver:
- default runtime path that can actually attempt SWE-bench-style software tasks end-to-end
- benchmark reruns showing not just better control behavior but actual task-solving capability

---

## 21. Success criteria for v7

v7 is successful when the following are true:

### 21.1 Execution-core reality

For a real software task, Crucible can provide the worker with:
- the task itself
- repo context
- failure context
- prior strategy context

not just a test command.

### 21.2 Meaningful retries

Across repeated attempts, the system can show:
- what changed
- why it changed
- why the next strategy differs

### 21.3 Environment honesty

A repo is not considered “ready” unless the intended validation surface can actually run.

### 21.4 Runtime separation remains clean

The worker does software work.
The runtime validates and governs.

### 21.5 SWE-bench no longer exposes the same structural failure

A benchmark failure may still happen, but it should fail because the software problem was hard, not because the runtime only re-ran verification commands.

---

## 22. Non-goals for v7

v7 is **not** trying to:
- replace the thin v6.1 control plane with a giant detailed ontology
- move validation authority into the worker
- eliminate runtime budgets or blocker semantics
- pretend that better prompting alone solves the product gap

The point is not “more words to the LLM.”
The point is a real architecture for iterative software work.

---

## 23. The blunt summary

v5.3-v6.1 built a runtime that is increasingly good at saying:
- what happened
- what failed
- whether we should continue
- whether we are stuck
- whether we should stop

That is the control plane.

But Crucible still needs the thing that can actually say:
- here is the repo
- here is the bug
- here is what I think is wrong
- here is the patch I made
- here is the test result
- here is what I will try next

That is the execution core.

**v7 is the spec that makes that execution core first-class.**

The architecture after v7 should be easy to describe:

- **Control plane:** owns loop policy, state, evidence, budgets, truthfulness
- **Execution core:** owns software problem-solving inside the loop
- **Validation:** independently checks whether claimed progress is real

That is the shape Crucible needs if it is going to become the software factory it was originally meant to be.
