# Agentic Harness v5.2 — Final Holistic Review

**Date:** 2026-04-06
**Reviewer:** Final holistic implementation review against PRD v5.2, Technical Design v5.2, and EXECUTION_PLAN v3

## Overall verdict

**PARTIALLY ACHIEVED**

The repository delivers a strong **foundation implementation** of the v5.2 harness spine: deterministic state contracts, ledgering, ambiguity/failure primitives, validation machinery, run-graph semantics, scheduler/memory foundations, isolated worktrees, resumable greenfield bootstrap, and optional accelerator abstractions. The code is real, the tests are substantive, and the implementation intent is clearly aligned with the source docs.

However, the full **product intent** from the PRD is only partially achieved because the repo stops short of a true end-to-end harness that autonomously takes a chat request, drives decomposition/orchestration, executes real worker runs through a common backend interface, integrates outputs, and exposes an operator-facing control/query surface. Several major promises are present as contracts or focused modules, but not yet assembled into a full working system.

Full test result observed during this review:
- `uv run pytest tests/ -v`
- **349 passed, 0 failed**

---

## PRD intent coverage

### Goal: chat-native delegation of substantial software work
**Status: PARTIAL**

**Evidence**
- The repo contains the harness internals needed for delegation, but no chat/control layer implementation.
- There is no module that turns natural-language user input into a full build campaign.
- No orchestrator exists that binds intent intake → ambiguity → spec → decomposition → execution → validation → summary.

**Assessment**
- The implementation supports the back-end substrate for chat-native delegation.
- It does **not** yet demonstrate the PRD’s core user promise: “send a concise description from phone and the system autonomously builds a functional, validated implementation with minimal back-and-forth.”

### Goal: spec-ambiguity gate before implementation
**Status: PARTIAL**

**Evidence**
- `src/agentic_harness/ambiguity/gate.py` implements `CLEAR | CLARIFY | SPLIT | DEFER` with fail-closed severity handling.
- Tests exist for normal and adversarial ambiguity cases.

**Assessment**
- The ambiguity **contract** is implemented well.
- What is missing is integration into a real intake/spec workflow. There is no higher-level harness loop that enforces “ambiguity gate before implementation” across the whole system.

### Goal: sub-agent-first execution and sub-agent management cluster
**Status: PARTIAL**

**Evidence**
- `runner/run_graph.py` implements parent/child ownership, blocking vs detached children, cancellation propagation, persistence, and partial outputs.
- `runner/spawn_controller.py` implements role templates, timeout tracking, active-run bookkeeping, and rehydration.
- `runner/circuit_breaker.py` implements rejection ledger and anti-loop behavior.

**Assessment**
- The structural semantics are present.
- But there is no real sub-agent backend wired into the controller, no progress/steering API, and no actual OpenClaw execution adapter. `SpawnController` defaults to a stub spawn function unless injected.
- This satisfies “management cluster foundation,” not “first-class live sub-agent orchestration” in the product sense.

### Goal: existing-project support
**Status: PARTIAL**

**Evidence**
- `workflows/intake.py` inspects repos and surfaces uncertainty instead of hallucinating.
- `workflows/worktree.py` provides isolated git worktrees with persistence/reconciliation.
- Tests cover clean/messy/broken/ambiguous repo handling and worktree isolation.

**Assessment**
- Repo inspection and isolation are real.
- Missing is the iterative change/test/integrate loop inside an existing codebase. The harness does not yet take an existing repo task through decomposition, execution, review, integration, and completion end-to-end.

### Goal: greenfield bootstrap support
**Status: PARTIAL**

**Evidence**
- `workflows/greenfield.py` bootstraps resumable Python projects with `uv`, README, CI, git init, initial commit.
- `workflows/first_working_version.py` enforces a runnable proof gate with anti-forgery checks.

**Assessment**
- Strongly implemented for a narrow slice.
- But the PRD/technical design explicitly call for local repo + remote GitHub repo creation when credentials are available. This repo does **not** create remote GitHub repos.
- Greenfield defaults are also limited to Python project variants, not a broader stack-selection policy.

### Goal: common execution interface, engine-agnostic core, optional accelerators
**Status: PARTIAL**

**Evidence**
- Phase 6 provides `BackendAdapter`, `BackendCapabilityMatrix`, `Router`, and `InMemoryAdapter`.
- Capability routing and fallback are tested.

**Assessment**
- The abstraction exists.
- Major gaps:
  - It does not match the technical design interface exactly.
  - There is no OpenClaw sub-agent backend implementation.
  - There is no real Claude Code or Codex adapter—only in-memory simulation.
  - `SpawnController` is not integrated with the adapter/router stack.

### Goal: validation and spec-traceable completion
**Status: MOSTLY SATISFIED AT COMPONENT LEVEL, PARTIAL AT SYSTEM LEVEL**

**Evidence**
- `validation/criterion.py`, `validator.py`, `ladder_executor.py`, `artifact.py`, `anti_vacuity.py`, `reviewer.py`, and `run_registry.py` implement a serious validation model.
- Validation is fail-closed, provenance-aware, anti-vacuity-aware, and reviewer-structured.
- Tests are deep and adversarial.

**Assessment**
- This is one of the strongest parts of the implementation.
- Missing is full build-level completion wiring: no orchestrator composes validation, review, integration, and completion across a real task graph.

### Goal: long-run continuity, hybrid memory, resumability
**Status: PARTIAL TO STRONG FOUNDATION**

**Evidence**
- Persistent state models exist.
- Ledger is append-only and restart-safe.
- Run graph, scheduler, ladder executor, memory store, worktree manager, and greenfield bootstrap all persist and reload state.
- `memory/memory_store.py` clearly separates harness-owned memory from host memory and validates provenance.

**Assessment**
- The persistence substrate is real and well-aligned with the PRD.
- What is missing is the build-level continuation policy that uses these pieces together in a live autonomous loop.

### Goal: resource-aware scheduler
**Status: SATISFIED AS FOUNDATION**

**Evidence**
- `scheduler/machine_profile.py`, `intensity.py`, and `scheduler.py` implement machine profiling, workload classification, headroom-aware scheduling, and persistence.

**Assessment**
- This meets the stated “simple but practical heuristic” bar for a foundational scheduler.
- It is not yet tied into real run dispatch/orchestration.

### Goal: human interruptibility / query surface
**Status: PARTIAL**

**Evidence**
- Active-run visibility exists in the run graph/controller model.
- State is deterministic and queryable in principle.

**Assessment**
- There is no actual operator API or chat-facing control surface for “what’s active?”, “what’s blocked?”, redirect, stop, reshape, etc.
- The underlying data exists; the user-facing capability does not.

### Goal: explicit failure handling and anti-loop protection
**Status: SATISFIED AS FOUNDATION**

**Evidence**
- `failures/taxonomy.py` deterministically maps 8 failure classes to actions and retry-budget semantics.
- `runner/circuit_breaker.py` tracks semantically repeated failures and known-bad approaches.

**Assessment**
- Strong implementation of the control primitives.
- Still only partially productized because these are not connected to a real orchestration loop.

### Goal: run-graph, integration, and completion semantics
**Status: PARTIAL**

**Evidence**
- Run-graph semantics are explicit.
- Validation completion semantics are explicit.
- `IntegrationState` exists in `state/models.py`.

**Assessment**
- Dedicated integration **policy** is described in docs, but there is no integration engine/module that performs fan-in, merge ordering, reconciliation, or post-integration revalidation.
- This is a key missing piece relative to the PRD release criteria.

### Key user/operator outcomes
**Achievable now**
- Persist and validate harness state deterministically.
- Analyze ambiguity and classify failures.
- Manage run graph semantics in memory/persistence.
- Schedule workloads conservatively.
- Store harness-owned lessons safely.
- Inspect existing repos and bootstrap a Python/uv project with CI and a strict first-working-version proof gate.

**Not yet achievable as promised**
- End-to-end autonomous software project execution from a concise chat request.
- Real sub-agent execution through a live backend.
- Full existing-repo implementation loop.
- Full greenfield local+remote bootstrap with GitHub creation.
- Operator-visible steering/status surface.
- Integrated task graph completion across execution, review, merge, and final summary.

---

## Technical design fidelity

## Component-by-component

### Conversation / control layer
**Status: MISSING**

The technical design names this as a major layer. There is no implementation of chat interaction, clarification UX, status presentation, interruption handling, or steering commands.

### Planning / orchestration layer
**Status: MOSTLY MISSING**

There is no central orchestrator that:
- converts intent into spec/tasks/run plans
- decides when to proceed vs clarify vs recover vs escalate
- attaches review/integration/salvage behavior at the build level

What exists are lower-level modules that such an orchestrator would use.

### Deterministic control layer
**Status: STRONGLY PRESENT**

**Evidence**
- State contracts: `state/models.py`
- Ledger: `ledger/ledger.py`
- Failure taxonomy: `failures/taxonomy.py`
- Validation bookkeeping: `validation/*`
- Scheduler: `scheduler/*`
- Memory persistence: `memory/memory_store.py`

This is the clearest design match in the repo.

### Execution layer
**Status: PARTIAL**

**Present**
- Run graph semantics
- Spawn controller
- Accelerator abstraction
- In-memory adapters

**Missing / deviating**
- No OpenClaw sub-agent backend despite being the specified primary v5.2 backend.
- No real inline deterministic backend abstraction as a first-class backend.
- No integration between `SpawnController` and the phase-6 backend adapter/router stack.

### Project memory / evidence layer
**Status: STRONGLY PRESENT**

**Evidence**
- Append-only ledger
- Artifact refs with hashing/integrity
- Run registry provenance binding
- Memory store with provenance-gated lessons and injection audit trail
- Validation persistence

This matches the design well.

### State contracts
**Status: PRESENT, WITH MINOR SHAPE DRIFT**

All required state objects are present:
- `ProjectState`
- `BuildState`
- `TaskState`
- `RunState`
- `ValidationState`
- `IntegrationState`

Minor note: some field typing/shape choices differ from the design’s conceptual contracts, but the required entities and persistence behavior are there.

### Ledger, event, and artifact model
**Status: MOSTLY PRESENT**

**Evidence**
- Append-only JSONL ledger with monotonic sequence numbers and corruption handling.
- Named event types from the design are implemented.
- Artifact refs are typed and integrity-checked.

**Gap**
- The explicit consume/produce artifact chain is not implemented as a single build loop; it exists as separate modules.

### Spec and ambiguity system
**Status: PARTIAL**

**Match**
- Output contract and classification behavior are aligned.

**Gap**
- No implemented spec creation/update module.
- No ambiguity-to-spec-to-task pipeline.

### Run graph semantics
**Status: STRONG MATCH**

`runner/run_graph.py` closely follows the design around ownership, detachment, cancellation, partial outputs, and persistence.

### Worker roles
**Status: PRESENT**

Builder, reviewer, debugger, researcher, integrator, and salvage roles are represented in enums/templates.

### Timeout salvage
**Status: PARTIAL**

There is timeout detection and partial artifact handling, but not a full salvage policy engine that decides between resume/split/inline/escalate in the way the design describes.

### Validation and review system
**Status: STRONG MATCH AT MODULE LEVEL**

This area is highly faithful:
- verification triples
- must-pass vs informational semantics
- anti-vacuity
- reviewer schema
- completion gating
- provenance verification

### Integration policy
**Status: MOSTLY MISSING IN CODE**

The design requires explicit fan-in/integrator behavior and post-integration revalidation. The repo defines `IntegrationState`, but does not implement a concrete integration workflow or merge engine.

### Scheduler and resource policy
**Status: GOOD FOUNDATIONAL MATCH**

Machine profiling, intensity classification, and headroom-aware dispatch are implemented and tested.

### Long-run autonomy and user control
**Status: PARTIAL**

Persistence and control primitives exist, but the actual autonomous loop and user query/control surface are not implemented.

### Execution backend interface
**Status: PARTIAL / DEVIATED**

The technical design specified:
- `spawn`
- `send`
- `poll`
- `collect`
- `kill`

The implemented `BackendAdapter` supports:
- `spawn`
- `poll`
- `collect`
- `kill`

It does **not** include `send`, and the interface is separated from the Phase 2 spawn controller rather than serving as the single backend abstraction underneath it. So the design intent is partially met, but the architecture is not yet fully unified.

---

## Execution plan completeness

## Phase-by-phase

### Phase 1 — Deterministic substrate
**Implementation status: COMPLETE**
**Validation-packet completeness: PARTIAL**

**Evidence**
- Code is present and tested.
- `docs/validation/phase-1/validation-matrix.md`, `adversarial-review.md`, and `signoff.md` exist.

**Gaps vs plan packet requirements**
- The execution plan called for additional artifacts such as state fixtures, ledger logs, ambiguity corpus report, and failure taxonomy report. Those exact artifacts/directories are not all present in the packet as named.

### Phase 2 — Sub-agent management cluster
**Implementation status: MOSTLY COMPLETE AS FOUNDATION**
**Validation-packet completeness: PARTIAL**

**Evidence**
- Code and tests exist for run graph, circuit breaker, and spawn controller.
- `adversarial-review.md` and `signoff.md` exist.

**Gaps**
- No `validation-matrix.md` file in `docs/validation/phase-2/`.
- Required lifecycle traces / cancellation logs / salvage transcripts / active-run visibility reports are not all present as named artifacts.

### Phase 3 — Validation and review foundation
**Implementation status: COMPLETE**
**Validation-packet completeness: STRONGEST OF ALL PHASES, STILL NOT FULLY PLAN-COMPLETE**

**Evidence**
- Code is strong and heavily tested.
- `validation-matrix.md` exists.
- Extensive adversarial review history exists (`adversarial-review*.md`).
- `signoff.md` exists.

**Gaps**
- The plan called for explicit criterion-evidence map, anti-vacuity report, reviewer schema examples, blocked-signoff example, raw transcripts. Some of this exists implicitly in code/tests/reviews, but not all named artifacts are present as standalone packet files.

### Phase 4 — Scheduling and memory foundation
**Implementation status: COMPLETE AS FOUNDATION**
**Validation-packet completeness: PARTIAL**

**Evidence**
- Code and tests exist.
- `adversarial-review*.md` and `signoff.md` exist.

**Gaps**
- No `validation-matrix.md` file in `docs/validation/phase-4/`.
- Required machine-profile report, scheduler stress logs, resource timeline logs/charts, lesson persistence report, and memory injection transcript are not present as named packet files.

### Phase 5 — Unified project workflows
**Implementation status: PARTIAL**
**Validation-packet completeness: PARTIAL**

**Evidence**
- Intake, worktree, greenfield bootstrap, and first-working-version gate exist.
- `adversarial-review*.md` and `signoff.md` exist.

**Gaps in implementation**
- Not truly “unified project workflows” yet; there is no shared orchestrated loop for existing + greenfield work.
- No GitHub repo creation.
- Greenfield support is Python/uv-specific, not generalized stack selection.

**Gaps in validation packet**
- No `validation-matrix.md` file in `docs/validation/phase-5/`.
- Required intake reports, worktree traces, CI outputs/links, interrupted-bootstrap recovery transcript, and first-working-version proof artifacts are not present as named deliverables.

### Phase 6 — Optional accelerators
**Implementation status: PARTIAL**
**Validation-packet completeness: PARTIAL**

**Evidence**
- Capability matrix, adapter abstraction, router, and in-memory adapter exist.
- `adversarial-review*.md` and `signoff.md` exist.

**Gaps in implementation**
- No Claude Code adapter.
- No Codex adapter.
- No OpenClaw sub-agent backend.
- No real backend parity beyond in-memory simulation.

**Gaps in validation packet**
- No `validation-matrix.md` file in `docs/validation/phase-6/`.
- Required capability matrix report, parity report, failover traces, and unsupported-capability rejection examples are not all present as named artifacts.

## Blocking gates and signoff packets overall

### Cleared in substance
- Most module-level behavioral gates appear satisfied through the test suite.
- The repository does substantively implement many of the phase goals.

### Not fully cleared per execution-plan process discipline
- The execution plan required rigorous per-phase validation packets with raw evidence artifacts.
- Those packets are **incomplete/inconsistently materialized**, especially in phases 2, 4, 5, and 6.
- So the answer to “every phase’s validation matrix satisfied, every blocking gate cleared, signoff packets present for every phase?” is:
  - **Signoff packets present for every phase:** yes, at least minimally.
  - **Validation matrices present for every phase:** no.
  - **Required packet artifacts present for every phase:** no.
  - **Therefore execution-plan completeness:** **PARTIAL**, not full.

---

## Gaps and debt

## Concrete gaps vs source docs

1. **No top-level orchestrator/build loop**
   - Missing the core system that composes intake → ambiguity → spec → decomposition → execution → validation → review → integration → completion.

2. **No conversation/control layer**
   - No chat-facing control/query/status/interruptibility implementation.

3. **No spec creation/update pipeline**
   - Ambiguity is implemented, but there is no spec authoring or spec-maintenance module.

4. **No task decomposition engine**
   - `TaskState` exists, but there is no decomposer that generates tasks from specs.

5. **No real backend integration**
   - No OpenClaw backend, no Claude Code adapter, no Codex adapter.
   - Phase 6 uses simulated in-memory adapters only.

6. **Backend architecture not unified**
   - Phase 2 controller and Phase 6 adapters/router are separate paths rather than one common execution spine.

7. **No integration engine**
   - No code to perform fan-in, conflict resolution, merge ordering, or post-integration validation.

8. **Greenfield remote repo creation missing**
   - PRD/design require creating remote GitHub repo when credentials are available; implementation only creates local repo + CI files + initial commit.

9. **Greenfield stack selection is narrow**
   - Design calls for choosing reasonable stacks; implementation supports Python-only project types.

10. **Existing-project workflow is incomplete**
   - Intake and worktrees exist, but not the actual iterative implementation/review/integration loop.

11. **Update cadence / user visibility missing**
   - No start/milestone/blocker/final update mechanism.

12. **Execution-plan evidence packets are incomplete**
   - Several required validation artifacts are absent or only implied by tests.

## Stubbed / simplified / in-memory-only areas

- `ambiguity/gate.py` is a classification contract, not a real request-analysis system.
- `accelerators/adapters.py` uses `InMemoryAdapter` as the reference implementation.
- `spawn_controller.py` has no concrete real worker launcher by default.
- `scheduler.py` uses fixed per-intensity cost tables rather than observed runtime adaptation.
- `IntegrationState` exists without a corresponding integration workflow implementation.

## What would be needed for production-ready vs foundation-complete

To move from “foundation complete” to “production-ready v5.2 intent achieved,” the next work should be:
- implement a real orchestrator that binds all phases into one build loop
- implement spec generation/update and task decomposition
- unify spawn controller with the execution backend interface
- add a real OpenClaw sub-agent backend
- add a real inline deterministic backend
- implement integration/fan-in/post-integration validation workflow
- add chat/operator control surface for status, steer, stop, redirect
- add remote GitHub creation and failure-safe external side-effect handling
- materialize full execution-plan validation packets with raw artifacts/logs

---

## Semantic cohesion

## Do the phases work together?
**Answer: partially.**

The repo is **not** just a bag of isolated modules; there is meaningful conceptual cohesion:
- state models define the durable entities
- ledger records transitions
- run graph/controller manage execution semantics
- validation modules enforce evidence-backed completion
- scheduler/memory provide runtime continuity mechanisms
- workflows add repo/bootstrap primitives
- accelerator abstractions introduce backend portability

But the cohesion is still mostly **architectural adjacency**, not yet a single executable end-to-end harness.

## Realistic end-to-end trace through the code

A plausible intended flow can be traced as follows:

1. **Project inspection**
   - `workflows/intake.inspect_repo()` inspects an existing repo and surfaces uncertainty.

2. **Ambiguity classification**
   - `ambiguity/gate.classify_ambiguity()` determines whether the request is clear enough to proceed.

3. **Durable state setup**
   - `state/models.py` supplies `ProjectState`, `BuildState`, `TaskState`, `RunState`, `ValidationState`, `IntegrationState`.
   - `ledger/ledger.py` can record `spec.created`, `task.created`, `run.spawned`, etc.

4. **Execution semantics**
   - `runner/run_graph.py` defines parent/child runs and partial output handling.
   - `runner/spawn_controller.py` can track active runs and timeouts.
   - `runner/circuit_breaker.py` can prevent repeated bad retries.

5. **Validation**
   - `validation/criterion.py` and `validator.py` enforce must-pass criteria with provenance-aware evidence.
   - `validation/ladder_executor.py` executes rung-by-rung validation.
   - `validation/reviewer.py` structures reviewer outputs.
   - `validation/anti_vacuity.py` checks that the implementation is not fake.

6. **Memory and continuity**
   - `memory/memory_store.py` can store lessons with provenance and inject them into future runs.

7. **Greenfield path**
   - `workflows/greenfield.bootstrap_greenfield()` scaffolds a Python/uv repo.
   - `workflows/first_working_version.check_first_working_version()` enforces proof of runnable state.

This is a coherent story.

## Integration gaps between phases

The missing glue is substantial:
- no actual spec artifact creation/update step
- no decomposition from spec to `TaskState`
- no controller that schedules tasks onto backends
- no path from `SpawnController` into `BackendAdapter`/`Router`
- no integration/fan-in stage after parallel work
- no completion summary generator at build scope

So the phases **conceptually fit**, but they do not yet **operate together as one harness**.

---

## Recommendations

1. **Build the orchestrator next**
   - This is the highest-leverage missing layer.
   - It should own the unified loop for both existing and greenfield projects.

2. **Unify execution abstractions**
   - Make the phase-6 backend interface the single substrate under phase-2 spawn/control semantics.
   - Add `send` if interactive run steering remains part of the design.

3. **Implement the OpenClaw backend first**
   - The docs explicitly position this as the primary v5.2 backend.
   - Without it, the product intent remains mostly theoretical.

4. **Add spec + decomposition modules**
   - The ambiguity gate is not enough; the harness needs a real spec artifact and task-plan generator.

5. **Implement integration/fan-in as a first-class module**
   - This is the major architectural hole relative to the design and PRD completion semantics.

6. **Complete greenfield support to spec**
   - Add remote GitHub repo creation and failure-safe handling when credentials are present.
   - Decide whether broader stack support is in scope for v5.2 or explicitly narrow the docs.

7. **Materialize the validation packets exactly as the execution plan requires**
   - Especially `validation-matrix.md` for phases 2, 4, 5, and 6.
   - Add the raw logs/reports/transcripts named in the execution plan so signoff is evidence-complete, not just test-complete.

8. **Add a minimal operator surface**
   - Even a deterministic CLI/API facade for “active / blocked / finished / remaining / stop / redirect” would close an important PRD gap.

---

## Bottom line

If the question is **“Did we build the full product promised by the PRD?”** the answer is **no, not yet**.

If the question is **“Did we build the core deterministic foundations and several critical workflow components needed for that product?”** the answer is **yes, emphatically**.

That is why the right holistic verdict is:

**PARTIALLY ACHIEVED**
