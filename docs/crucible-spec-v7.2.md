# Crucible Specification v7.2

**Status:** Draft for review  
**Date:** 2026-04-11  
**Supersedes:** `docs/crucible-spec-v7.md` and `docs/crucible-spec-v7.1.md` where they conflict  
**Read with:**
- `docs/architecture.md`
- `docs/crucible-spec-v6.1.md`
- `docs/crucible-spec-v7.1.md`
- `docs/references/agentic-toolkit-architecture-v4.6.2.md`
- `src/crucible/runtime/run_executor.py`
- `src/crucible/runtime/local_shell_adapter.py`
- `tests/runtime/test_closed_loop_runtime_e2e.py`
- `tests/runtime/test_openclaw_tool.py`

---

## 1. Why v7.2 exists

v7 and v7.1 correctly identified the main gap: Crucible has built a meaningful **runtime/control-plane substrate**, but the default shipped path is still not yet a full **plan-first software factory**.

v7.2 exists to do three things more clearly than v7/v7.1:

1. **Separate what is already built from what is still missing, based on code and tests rather than aspiration.**
2. **Collapse redundancy** between the execution-core-first framing in v7 and the control-plane/execution-core split in v7.1.
3. **Define a concrete phased execution plan** for getting from the current runtime to the intended product.

---

## 2. Product and invocation model

Crucible is **library/runtime-first**.

That means:
- the durable execution semantics live in Python library code under `src/crucible/`
- the CLI is one surface over that runtime (`src/crucible/runtime/cli.py`)
- the OpenClaw tool wrapper is another surface (`src/crucible/runtime/openclaw_tool.py`)
- chat-facing usage should primarily come through:
  - an OpenClaw skill/tool front door, or
  - coding-agent style entry surfaces (Claude Code, Codex CLI, other agent front doors) that invoke Crucible as the execution substrate rather than replacing it

The user-facing intent is:

> “Use Crucible to build/fix this.”

That should route into Crucible’s runtime surfaces, create a durable run, and expose `run/status/watch/resume` semantics. The CLI remains important, but it is **not** the product boundary.

---

## 3. Architecture: what Crucible is

Crucible has three distinct layers.

### 3.1 Execution core
Owns task-local software work:
- repo inspection
- planning for the task
- code-change strategy
- bug investigation / reproduce / fix / verify discipline
- adapting to validator and reviewer findings

### 3.2 Control plane
Owns loop policy and durable truth:
- run state
- attempt typing
- next-action selection
- budgets and circuit breaking
- blocker semantics
- workspace lineage
- resume behavior

### 3.3 Validation / review / audit layer
Owns proof:
- verification execution
- review gates
- contract validity
- evidence manifests
- prompt / response / artifact history

Design rule:
- **execution core decides what software change to try next**
- **control plane decides whether the loop continues / shifts / pauses / stops**
- **validation/audit decides what evidence proves the claim**

---

## 4. What is already built in the repo today

The following are **implemented now** in code and covered by runtime tests:

### 4.1 Durable runtime surfaces
Implemented in:
- `src/crucible/runtime/run_store.py`
- `src/crucible/runtime/cli.py`
- `src/crucible/runtime/openclaw_tool.py`
- `src/crucible/runtime/resume_handler.py`
- `src/crucible/runtime/status_emitter.py`

What exists:
- durable run manifests, events, attempts, adapter state, result summaries
- CLI `run`, `status`, `watch`, `resume`, `lint-plan`
- OpenClaw tool surface with structured `run/status/watch/resume`
- restart-safe resume and workspace provenance checks

### 4.2 Closed-loop control-plane behavior
Implemented primarily in:
- `src/crucible/runtime/run_executor.py`
- `src/crucible/failures/*`
- `src/crucible/orchestrator/closed_loop_executor.py`

What exists:
- typed attempts (`build`, `repair`, `debug`, `review`, `salvage`, etc.)
- deterministic next-action selection after failure
- review as a real gate
- circuit-breaking / budget-aware continuation semantics
- failure packet creation and reuse
- workspace lineage (`fresh`, `repair_basis`, `salvage_inherit`)

### 4.3 Environment provisioning hooks
Present in the shipped path through:
- `ensure_existing_repo_environment(...)` calls from `run_executor.py`
- environment-related tests in `tests/runtime/test_closed_loop_runtime_e2e.py`
- error classification tests in `tests/runtime/test_failure_classification_v54.py`

### 4.4 OpenClaw bridge integration
Implemented in:
- `src/crucible/runtime/openclaw_adapter.py`
- `src/crucible/runtime/openclaw_bridge.py`
- `tests/runtime/test_openclaw_tool.py`

What exists:
- persisted sub-agent adapter state
- bridge-backed adapter flow
- tool wrapper integration for OpenClaw-initiated runs

### 4.5 Plan preflight / linting
Implemented in:
- `src/crucible/runtime/preflight.py`
- `src/crucible/runtime/plan_loader.py`

What exists:
- plan linting / normalization before run start
- task-definition shape validation

---

## 5. What is not yet built enough

These are the main gaps visible in the current code.

### 5.1 No true plan-first execution gate in the shipped runtime
There is plan linting, but not yet a first-class planning subsystem that:
- inspects the repo
- resolves ambiguity
- creates a durable plan artifact
- validates dependencies between tasks
- blocks execution until the plan is accepted as structurally complete

### 5.2 The default local path is still verification-command-driven
`LocalShellAdapter` explicitly treats `AdapterRunSpec.prompt` as the verification command, and `run_executor.py` currently wires criterion verification commands directly into adapter runs.

This is honest, but it is not yet a real execution core.

### 5.3 Missing first-class execution-packet model
The runtime does not yet construct a durable worker packet containing:
- task goal
- repo summary
- relevant files
- prior failed strategies
- review requirements
- validation policy
- task type / bug-fix state

### 5.4 Missing prompt/response audit logs for every worker attempt
The runtime persists attempts, events, and evidence, but not yet a full prompt/response ledger for all build/review attempts as a first-class requirement.

### 5.5 Missing semantic rejection ledger and strategy memory
There is some history/evidence, but not yet a distinct semantic artifact that says:
- what was tried
- why it failed
- what must not be retried unchanged
- what hypothesis should change next

### 5.6 Missing first-class bug-fix protocol state in runtime
The repo has strong guidance in docs/specs, but the runtime does not yet enforce structured bug-fix state such as:
- reproduce test written
- reproduce fails before fix
- reproduce passes after fix
- investigation summary

### 5.7 Missing tiered context + reviewer policy subsystems
Reviewer contracts exist, but typed reviewer policy, context tiering, and a dedicated planning/review/audit subsystem layout are not yet fully realized as code.

---

## 6. Non-negotiable v7.2 behavior target

Every software task should eventually run through this shape:

```text
intake
→ ambiguity check
→ repo/context inspection
→ durable plan creation
→ plan validation gate
→ task decomposition
→ build attempt
→ validation
→ review
→ repair/debug if needed
→ integrate
→ ship/return
→ learn
```

A verification command is **validation input**, not the primary worker prompt.

---

## 7. Phased execution plan

This is the required implementation order.

### Phase 1 — Plan system and execution packet foundation
**Build first:**
- `planning/` subsystem
- ambiguity detection
- durable `plan.json`
- plan validation gate
- `ExecutionPacket` model

**Depends on:** existing preflight + run store  
**Exit criteria:**
- no run starts without a validated durable plan
- each task has explicit success criteria, dependencies, validation policy, review policy
- runtime can persist and display the plan artifact

### Phase 2 — Real execution-core default path
**Build:**
- worker-facing execution packet builder
- repo summary / relevant-files extraction
- replace verification-command-as-worker-prompt in the default solving path
- structured worker result schema

**Depends on:** Phase 1  
**Exit criteria:**
- default build path receives a software task packet, not only a shell command
- retries are materially informed by prior evidence
- local shell remains available as validation baseline, not the only solving path

### Phase 3 — Bug-fix protocol and strategy memory
**Build:**
- bug-fix task type
- reproduce/fix/verify state fields
- rejection ledger
- strategy memory artifact
- stronger repeated-failure handling

**Depends on:** Phases 1-2  
**Exit criteria:**
- bug-fix tasks can prove reproduce → fix → verify in runtime state
- failed strategies are persisted semantically and injected into later attempts

### Phase 4 — Review, validation policy, and audit
**Build:**
- typed reviewer policies/tiers
- deterministic audit checklist support
- prompt/response logs per attempt
- stronger validation-policy artifact chain

**Depends on:** Phases 1-3  
**Exit criteria:**
- every attempt has inspectable prompt/result audit history
- reviewer policy is declared per task
- must-pass vs informational gates are explicit and persisted

### Phase 5 — OpenClaw/library productization
**Build:**
- first-class OpenClaw skill/tool entry
- clear library API for non-CLI embedding
- status/watch/resume UX polish across chat surfaces
- ship/integration docs

**Depends on:** Phases 1-4  
**Exit criteria:**
- chat-native “use Crucible” flow enters the real runtime
- CLI, library API, and OpenClaw surface all converge on the same execution semantics

### Phase 6 — Evaluation and hardening
**Build:**
- benchmark reruns
- benchmark-specific environment hardening
- docs + architecture cleanup
- operational lessons integration

**Depends on:** Phases 1-5  
**Exit criteria:**
- benchmark failures are due to problem difficulty, not hollow execution
- docs accurately match code
- runtime is explainable as shipped architecture, not just roadmap

---

## 8. Phase gates / release gates

A phase is not complete until:
- code exists
- tests prove the behavior
- docs describe the actual behavior
- artifacts are inspectable on disk

Additional gate rules:
- no doc claim about “already built” without code + test evidence
- no prompt/audit claim without persisted artifacts
- no “plan-first” claim until the runtime can reject runs lacking a valid durable plan artifact
- no “software factory” claim until the default path performs real task-aware execution rather than primarily replaying verification commands

---

## 9. Blunt summary

Crucible already has a real runtime substrate:
- durable run state
- typed attempts
- next-action selection
- review gating
- workspace lineage
- OpenClaw tool/bridge surfaces
- resume/status/watch semantics

What it does **not** yet fully have is the missing top half of the product promise:
- plan-first execution
- execution packets
- semantic strategy memory
- enforced bug-fix protocol
- prompt/response audit logs
- a default solving path that is truly repo-aware and software-task-aware

That is what v7.2 makes explicit, and why the build order above matters.
