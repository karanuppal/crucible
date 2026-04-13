# Crucible Specification v7.3

**Status:** Build-ready implementation spec  
**Date:** 2026-04-11

---

## Deliverables checklist
- [x] Read `docs/crucible-spec-v7.2.md`
- [x] Read `docs/reviews/crucible-spec-v7.2-review.md`
- [x] Read `docs/crucible-spec-v7.1.md`
- [x] Inspect current repo/runtime reality to separate built vs not-yet-built behavior
- [x] Produce a standalone v7.3 spec with no normative dependency on older specs
- [x] Add explicit boundary section for loop/state-machine/LLM/prompt ownership
- [x] Add stronger markdown architecture flow
- [x] Define minimal contracts for `plan.json`, `ExecutionPacket`, prompt/audit record, and strategy memory
- [x] Define embedding contract for OpenClaw, Claude Code, and Codex CLI
- [x] Preserve phased execution plan with phase gates and first-build order

---

## 1. Purpose

Crucible is a **library-first durable execution substrate for software tasks**.

Its job is not to be a chat UI and not to be a thin wrapper around a coding agent. Its job is to take a software task, persist the run, execute attempts with evidence, validate results, classify outcomes, and support `run/status/watch/resume` semantics regardless of which front door initiated the work.

The intended product truth is:

> OpenClaw, Claude Code, and Codex CLI may be how the user enters, but Crucible is the execution substrate underneath.

This document is standalone. Older specs may be useful historical context, but they are not normative for implementation.

---

## 2. Ground truth: what exists now vs what does not

### 2.1 Already implemented in repo

The current repo already has a meaningful runtime/control-plane substrate.

Implemented and evidenced in code/tests:
- Durable run storage, manifests, events, attempts, summaries
  - `src/crucible/runtime/run_store.py`
- CLI runtime surfaces
  - `src/crucible/runtime/cli.py`
  - supports `run`, `status`, `watch`, `resume`, `lint-plan`
- OpenClaw wrapper/tool surface
  - `src/crucible/runtime/openclaw_tool.py`
- Resume and status plumbing
  - `src/crucible/runtime/resume_handler.py`
  - `src/crucible/runtime/status_emitter.py`
- Closed-loop typed attempt execution
  - `src/crucible/runtime/run_executor.py`
  - `src/crucible/orchestrator/closed_loop_executor.py`
- Failure packets, next-action selection, retry typing, circuit breaking, workspace lineage
  - `src/crucible/failures/*`
  - `src/crucible/policy/*`
  - `src/crucible/state/*`
- OpenClaw bridge-backed adapter path
  - `src/crucible/runtime/openclaw_bridge.py`
  - `src/crucible/runtime/openclaw_adapter.py`
- Runtime tests that prove the loop is real, not aspirational
  - `tests/runtime/test_closed_loop_runtime_e2e.py`
  - `tests/runtime/test_openclaw_tool.py`

### 2.2 Not yet implemented enough

These are still missing as first-class architecture:
- true plan-first execution gate with durable planning artifact generation
- first-class `ExecutionPacket` object passed into a real task-aware worker path
- prompt-policy snapshot + exact prompt/audit ledger persisted for each attempt
- semantic strategy memory / rejection ledger injected into retries
- enforced bug-fix protocol state (`reproduce -> fix -> verify`)
- a default solving path that is genuinely repo-aware rather than primarily wiring verification commands into the default adapter flow

### 2.3 Honest current default path

`LocalShellAdapter` is still an **honest verification baseline**, not the final execution core. It treats `AdapterRunSpec.prompt` as the command to run. That is useful for truthful validation and testability, but it is not the end-state architecture for task-aware software execution.

---

## 3. Why this is not one loop

### 3.1 Why not one giant loop?

Because global workflow policy and task-local software execution are different problems.

A single loop collapses:
- task selection
- policy selection
- prompt-family/model selection
- code generation/editing
- validation
- retry choice
- escalation/blocking
- terminal classification

That creates a god-loop with weak failure isolation and poor auditability.

### 3.2 Are these two state machines?

Yes.

Crucible should be implemented as **two nested state machines**:
- **control plane** = outer workflow/run state machine
- **execution core** = inner task-execution state machine

The execution core is invoked by the control plane. It is not a peer that competes with it.

### 3.3 Where do LLM calls live?

LLM calls may exist in both layers, but they serve different purposes.

- **Control-plane LLM calls**: decomposition, ambiguity handling, policy selection, task shaping, escalation reasoning, summarization
- **Execution-core LLM calls**: codegen, editing, debugging, review, verification summaries, bounded local repair

Hard rule:
- **artifact-producing/code-changing calls belong in the execution core**
- **policy-selection calls belong in the control plane**

### 3.4 Where do prompt construction and prompt policy live?

This split must be explicit.

- **Prompt policy lives in the control plane**
  - prompt family
  - model routing
  - role definitions
  - budget/timeout/tool scope
  - review strictness
  - retry-mode policy
- **Prompt instantiation lives in the execution core**
  - inject task packet
  - inject repo context/files
  - inject failure evidence and prior strategies
  - build the exact attempt prompt body

Short version:
- control plane chooses the recipe
- execution core cooks the meal

---

## 4. Architecture flow

```text
USER / API / CHAT FRONT DOOR
  -> normalize request into Crucible run submission
  -> attach embedding metadata (surface, session, workspace, operator)

FRONT DOOR
  -> OPENCLAW TOOL / LIBRARY CALL / CLI SHIM
  -> validate input shape
  -> create or resume durable run

CONTROL PLANE
  -> intake goal or plan
  -> ambiguity check
  -> plan creation or plan ingestion
  -> plan validation gate
  -> task selection
  -> policy selection
  -> build ExecutionPacket
  -> dispatch to execution core
  -> ingest result
  -> choose next action: accept / repair / debug / review / block / escalate / stop

EXECUTION CORE
  -> build task-local context
  -> instantiate prompts from policy snapshot + packet + evidence
  -> run builder/fixer/reviewer/verifier attempts
  -> mutate workspace through adapter/backend
  -> collect evidence
  -> return structured result + artifacts + recommendation

VALIDATION / AUDIT
  -> run required validators
  -> evaluate review/verifier gates
  -> persist prompt and audit records
  -> produce inspectable evidence chain

STATE / ARTIFACTS
  -> run manifest
  -> plan.json
  -> attempt records
  -> failure packets
  -> prompt/audit records
  -> strategy memory / rejection ledger
  -> diffs / logs / test output / review reports / summaries
  -> status timeline / resume state
```

Design rule:
- front doors are replaceable
- control-plane semantics are shared
- execution-core semantics are shared
- state and artifacts are durable truth

---

## 5. Component responsibilities

### 5.1 Front door
Responsible for:
- receiving human/upstream intent
- mapping it to Crucible input contracts
- passing embedding metadata
- exposing status/watch/resume to the originating surface

Not responsible for:
- redefining run semantics
- inventing separate retry logic
- being the source of truth for run state

### 5.2 Control plane
Responsible for:
- ambiguity detection
- plan creation/ingestion/validation
- task ordering and dependency handling
- policy selection and budgets
- choosing next action after each result
- durable run-level state

### 5.3 Execution core
Responsible for:
- task-local context building
- exact prompt instantiation
- code changes / debugging / review / repair attempts
- packaging evidence and structured result

### 5.4 Validation and audit
Responsible for:
- validator stack declaration and execution
- prompt/result auditability
- evidence sufficiency determination
- reviewer/verifier acceptance or rejection

---

## 6. Minimal contracts

These are the minimum canonical artifacts for Phase 1-4 implementation.

### 6.1 `plan.json`

Purpose: durable plan artifact validated before real execution begins.

```json
{
  "plan_id": "plan-20260411-001",
  "run_id": "run-abc123",
  "project_id": "crucible",
  "build_id": "v7-3",
  "goal": "Implement requested software task",
  "source": {
    "submitted_by": "openclaw",
    "embedding_surface": "telegram",
    "embedding_session_ref": "topic-6442"
  },
  "status": "validated",
  "planning_version": "p1",
  "tasks": [
    {
      "task_id": "T1",
      "description": "...",
      "task_type": "bugfix",
      "dependencies": [],
      "acceptance_criteria": ["..."],
      "validation_policy": {
        "required_commands": ["pytest -q"],
        "must_pass": ["tests"],
        "informational": []
      },
      "review_policy": {
        "required": true,
        "tier": "standard"
      }
    }
  ],
  "global_policy": {
    "max_attempts_per_task": 4,
    "allow_human_clarification": true
  },
  "artifacts": {
    "repo_summary_ref": null,
    "ambiguity_report_ref": null
  }
}
```

Required invariants:
- no execution starts without `status = validated`
- every task declares dependencies, acceptance criteria, validation policy, and review policy
- plan is persisted on disk and visible in status surfaces

### 6.2 `ExecutionPacket`

Purpose: control-plane contract into the execution core for one task attempt series.

```json
{
  "packet_id": "xp-T1-01",
  "run_id": "run-abc123",
  "task_id": "T1",
  "attempt_series": 1,
  "task": {
    "task_type": "bugfix",
    "goal": "Fix login refresh failure",
    "acceptance_criteria": ["failing test passes", "no auth regression"]
  },
  "repo_context": {
    "workspace_path": "/tmp/...",
    "repo_summary_ref": "artifacts/repo-summary.json",
    "relevant_files": ["src/auth.py", "tests/test_auth.py"]
  },
  "policy_snapshot": {
    "prompt_family": "bugfix-standard",
    "model_route": "default",
    "attempt_budget": 4,
    "tool_scope": ["git", "pytest"],
    "review_tier": "standard"
  },
  "validation_inputs": {
    "required_commands": ["pytest tests/test_auth.py -q"],
    "must_pass": ["tests"]
  },
  "history": {
    "prior_failure_packets": ["..."],
    "strategy_memory_ref": "artifacts/strategy-memory.json"
  }
}
```

Required invariants:
- execution core receives packets, not vague free-form task strings
- every retry can reference prior failure evidence and strategy memory
- the packet is reconstructible from durable state

### 6.3 Prompt / audit record

Purpose: inspectable record of what policy was selected, how a prompt was instantiated, what model ran, and what came back.

```json
{
  "audit_id": "audit-attempt-003",
  "run_id": "run-abc123",
  "task_id": "T1",
  "attempt_id": "attempt-003",
  "attempt_type": "repair",
  "prompt_policy": {
    "family": "bugfix-standard",
    "version": "2026-04-11",
    "role": "fixer",
    "model_route": "default",
    "tool_scope": ["git", "pytest"]
  },
  "prompt_instantiation": {
    "packet_ref": "artifacts/execution-packet-T1.json",
    "included_files": ["src/auth.py", "tests/test_auth.py"],
    "included_evidence_refs": ["failure-packet-002.json"],
    "instructions_hash": "sha256:..."
  },
  "model_execution": {
    "provider": "anthropic",
    "model": "claude-sonnet",
    "started_at": "2026-04-11T16:00:00Z",
    "finished_at": "2026-04-11T16:02:10Z"
  },
  "result": {
    "outcome": "complete",
    "response_ref": "artifacts/raw-response-attempt-003.json",
    "files_touched": ["src/auth.py"],
    "commands_run": ["pytest tests/test_auth.py -q"]
  }
}
```

Required invariants:
- prompt family/version and exact attempt role are always persisted
- prompt construction is inspectable after the fact
- audit record points to artifacts rather than forcing giant blobs into the run manifest

### 6.4 Strategy memory / rejection ledger

Purpose: prevent repeated bad retries and persist semantic learning within a run.

```json
{
  "task_id": "T1",
  "run_id": "run-abc123",
  "entries": [
    {
      "attempt_id": "attempt-001",
      "attempt_type": "build",
      "strategy": "patched token refresh branch without preserving cookie path",
      "outcome": "rejected",
      "reason": "review_rejection",
      "do_not_repeat_without_change": true,
      "required_delta_for_retry": "preserve cookie path semantics",
      "evidence_refs": ["failure-packet-001.json", "review-001.json"]
    }
  ],
  "current_hypotheses": [
    "bug may be in refresh cookie persistence rather than token decode"
  ]
}
```

Required invariants:
- retries must be able to reference a durable rejection ledger
- the ledger records what failed and what must change before retry

---

## 7. Embedding contract: how Crucible sits underneath front doors

### 7.1 General rule

OpenClaw, Claude Code, and Codex CLI are **entry surfaces or worker backends**, not alternate truth systems.

All three must converge on the same durable Crucible concepts:
- run
- plan
- task
- attempt
- evidence
- status/watch/resume
- terminal result classification

### 7.2 OpenClaw

OpenClaw integration is already partially real via:
- `src/crucible/runtime/openclaw_tool.py`
- bridge-backed adapter plumbing

Contract:
- OpenClaw calls Crucible through the library/tool wrapper, not by inventing separate runtime semantics
- OpenClaw may supply:
  - `embedding_surface`
  - `embedding_session_ref`
  - `workspace_root`
  - spawn/wait callables for sub-agent execution
- Crucible owns:
  - run creation
  - durable state
  - attempt typing
  - result classification
  - status/watch/resume behavior

### 7.3 Claude Code

Claude Code should be supported as a backend/worker surface under Crucible, not as the system-of-record.

Contract:
- Crucible control plane builds the `ExecutionPacket`
- Crucible selects prompt family/model/budget policy
- Claude Code executes task-local attempts from that packet
- returned outputs are normalized into Crucible attempt/audit/evidence records
- resume/status truth stays in Crucible, not inside Claude Code session history

### 7.4 Codex CLI

Codex CLI should follow the same contract as Claude Code.

Contract:
- Crucible may invoke Codex CLI as an execution backend for build/repair/review roles
- Codex CLI receives task-local instructions derived from the `ExecutionPacket`
- file edits, tool runs, and summaries are ingested back into Crucible artifacts and attempt records
- Crucible remains responsible for retry policy, validation policy, and terminal classification

### 7.5 Required embedding boundary

Front doors may differ in UX, but not in authority.

Front doors can:
- submit work
- observe progress
- resume/steer/cancel
- host an execution backend

Front doors cannot become the authoritative owner of:
- run state
- policy snapshots
- attempt ledger
- evidence chain
- terminal semantics

---

## 8. Phase plan and first-build sequence

The sequence below preserves the v7.2 build order, but makes each phase implementation-sharp.

## Phase 1 — Plan system and durable plan gate

### Build
- `planning/` subsystem
- ambiguity detector
- durable `plan.json`
- plan validation gate in runtime entry path
- status surfaces that expose plan presence/validity

### Tests required
- run rejected when plan invalid or absent
- validated plan persisted on disk
- `status/watch/resume` expose plan state

### Exit criteria
- no real execution begins without validated `plan.json`
- every task in plan has dependencies, acceptance criteria, validation policy, review policy
- CLI/OpenClaw path can show the plan artifact

## Phase 2 — `ExecutionPacket` and real task-aware execution path

### Build
- `ExecutionPacket` model + serializer
- repo summary / relevant-files extractor
- packet builder from plan + run state
- migration away from verification-command-as-primary-worker-prompt in the default solving path
- structured execution result object

### Tests required
- packet contains repo context + policy snapshot + prior evidence refs
- task-aware backend path can run from packet
- default path no longer depends solely on shell command prompt wiring

### Exit criteria
- execution core receives packets, not only bare verification commands
- retries consume prior evidence and strategy refs
- local shell remains validation baseline, not the primary architecture claim

## Phase 3 — Strategy memory and bug-fix protocol

### Build
- bug-fix task-type state
- reproduce/fix/verify state fields
- strategy memory / rejection ledger artifact
- repeated-failure guardrails

### Tests required
- failed strategy is persisted and visible in next retry packet
- bugfix flow can prove reproduce -> fix -> verify
- unchanged rejected strategy cannot be replayed silently

### Exit criteria
- bug-fix tasks have explicit protocol state
- retry semantics use semantic memory, not only raw logs

## Phase 4 — Prompt policy, review policy, and audit ledger

### Build
- prompt family registry/snapshots
- prompt/audit record persistence per attempt
- typed reviewer policy tiers
- validator chain artifact model

### Tests required
- each attempt records prompt policy + instantiation metadata + model execution info
- reviewer policy is persisted per task
- must-pass vs informational validators are inspectable

### Exit criteria
- every attempt has inspectable prompt/audit trail
- review/validation policy is explicit and durable

## Phase 5 — Front-door productization

### Build
- stable library API for embedding
- explicit OpenClaw entry docs
- Claude Code backend adapter path
- Codex CLI backend adapter path
- UX polish for `run/status/watch/resume`

### Tests required
- all supported entry surfaces map to the same run semantics
- same run can be inspected independent of originating front door

### Exit criteria
- front doors differ only in invocation UX and backend choice
- Crucible remains the shared substrate underneath them

## Phase 6 — Evaluation and hardening

### Build
- benchmark reruns
- environment hardening
- docs cleanup against shipped architecture
- operational lessons integration

### Tests required
- benchmark failures can be attributed to model/task difficulty rather than architectural hollowness
- docs match observed artifact layout and runtime behavior

### Exit criteria
- architecture is explainable from shipped code and artifacts
- docs no longer over-claim

---

## 9. Release-gate rules

A phase is not complete until all are true:
- code exists
- tests prove behavior
- disk artifacts are inspectable
- docs match the shipped behavior

Additional hard gates:
- no “plan-first” claim until invalid/missing plans are rejected by runtime
- no “task-aware execution” claim until `ExecutionPacket` is real and used
- no “prompt-managed” claim until prompt policy snapshots and audit records persist on disk
- no “strategy memory” claim until rejection ledger artifacts affect retries
- no “front-door convergence” claim until OpenClaw/Claude Code/Codex CLI all map to the same durable run semantics

---

## 10. Priority ordering

Capabilities should be prioritized in this order:
1. durable runtime truth
2. plan gate
3. task-aware execution packet
4. semantic retry memory + bug-fix protocol
5. prompt/audit policy system
6. front-door/backend convergence
7. benchmark hardening

Reason: without durable truth + plan gate + real task packet, everything above is theater.

---

## 11. Final design conclusions

1. Crucible is library-first and runtime-first.
2. It should sit underneath OpenClaw, Claude Code, and Codex CLI rather than be replaced by them.
3. It should be two nested state machines: control plane outside, execution core inside.
4. Prompt policy belongs to the control plane.
5. Prompt instantiation and artifact-producing LLM calls belong to the execution core.
6. `plan.json`, `ExecutionPacket`, prompt/audit records, and strategy memory are the minimum missing first-class artifacts.
7. The current repo already proves durable runs, typed attempts, failure packets, review gating, workspace lineage, and OpenClaw integration plumbing.
8. The main architectural gap is not “make the runtime more real.” The runtime is already real. The gap is adding the missing plan-first, task-aware, audit-first top half so the default path becomes a genuine software factory substrate.
