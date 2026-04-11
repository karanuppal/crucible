# Crucible Specification v7.3.1

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
- [x] Add canonical `ExecutionResult` / `AttemptResult` contracts and run/task terminal enums
- [x] Add explicit state-transition semantics for control plane and bugfix protocol
- [x] Add strict backend-normalization appendix and prompt/audit persistence policy
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

### 6.3 `ExecutionResult`

Purpose: canonical contract from the execution core back to the control plane for one task-level execution series.

```json
{
  "run_id": "run-abc123",
  "task_id": "T1",
  "status": "task_succeeded",
  "terminal": true,
  "terminal_reason": "validation_and_review_passed",
  "recommended_transition": "accept",
  "attempt_count": 3,
  "final_attempt_id": "attempt-003",
  "current_bugfix_state": "verified",
  "summary": "Refresh-cookie regression fixed and verified.",
  "artifact_refs": {
    "attempts": ["artifacts/attempt-001.json", "artifacts/attempt-002.json", "artifacts/attempt-003.json"],
    "failure_packets": ["artifacts/failure-packet-002.json"],
    "validator_report": "artifacts/validator-report-T1.json",
    "review_report": "artifacts/review-T1.json"
  },
  "metrics": {
    "elapsed_seconds": 412,
    "backend_attempt_seconds": 377,
    "token_usage": 38211,
    "tool_calls": 17
  }
}
```

Required fields:
- `status`: one of `task_succeeded`, `task_failed`, `task_blocked`, `task_escalated`, `task_cancelled`
- `terminal`: must be `true` for `ExecutionResult`; non-terminal attempt outcomes live in `AttemptResult`
- `terminal_reason`: machine-readable reason explaining the terminal classification
- `recommended_transition`: one of the control-plane actions defined in §6.5
- `artifact_refs`: refs to the evidence chain sufficient for `status/watch/resume` and audit surfaces

Mapping rule:
- the execution core may recommend, but the control plane performs the state transition and is the only layer allowed to mark a task/run complete, blocked, escalated, or cancelled

### 6.4 `AttemptResult`

Purpose: canonical per-attempt record returned by any execution backend and durably persisted before control-plane evaluation.

```json
{
  "attempt_id": "attempt-003",
  "run_id": "run-abc123",
  "task_id": "T1",
  "attempt_index": 3,
  "attempt_type": "repair",
  "backend": "claude_code",
  "status": "complete",
  "started_at": "2026-04-11T16:00:00Z",
  "finished_at": "2026-04-11T16:02:10Z",
  "duration_seconds": 130,
  "summary": "Preserved cookie path semantics and reran auth tests.",
  "files_touched": ["src/auth.py"],
  "commands_run": ["pytest tests/test_auth.py -q"],
  "exit_code": 0,
  "evidence_refs": ["artifacts/pytest-attempt-003.txt", "artifacts/diff-attempt-003.patch"],
  "raw_output_ref": "artifacts/raw-response-attempt-003.json",
  "model_execution": {
    "provider": "anthropic",
    "model": "claude-sonnet",
    "internal_steps": 5
  },
  "backend_loop": {
    "performed_internal_multistep_reasoning": true,
    "performed_file_mutation": true,
    "performed_command_execution": true
  },
  "recommendation": "accept"
}
```

Required fields:
- identity: `attempt_id`, `run_id`, `task_id`, `attempt_index`, `attempt_type`, `backend`
- lifecycle: `status`, `started_at`, `finished_at`, `duration_seconds`
- work performed: `files_touched`, `commands_run`, `exit_code`, `backend_loop.*`
- evidence: `summary`, `evidence_refs`, `raw_output_ref`, `model_execution`
- recommendation: one of `accept`, `repair`, `debug`, `review`, `block`, `escalate`, `stop`

Attempt terminal-status enum:
- `pending`
- `running`
- `complete`
- `failed`
- `killed`
- `timed_out`
- `partial`

Normalization rule:
- this enum intentionally aligns with the current adapter parity contract in `src/crucible/accelerators/adapters.py`; backends may have richer native statuses, but they must map into this canonical set before Crucible persists the attempt

### 6.5 Task and run terminal statuses + transition semantics

Control-plane action enum:
- `accept`: task-level success proven; mark task succeeded and advance dependencies
- `repair`: retry with a materially different fix/build attempt
- `debug`: gather deeper evidence before another fix/build attempt
- `review`: run reviewer/verifier gate before accepting or rejecting
- `block`: stop on unmet prerequisite or environment constraint that is not solvable inside current authority
- `escalate`: hand to human/operator because policy or ambiguity requires external judgment
- `stop`: terminate by cancellation, budget exhaustion, or explicit operator stop

Task terminal-status enum:
- `task_succeeded`
- `task_failed`
- `task_blocked`
- `task_escalated`
- `task_cancelled`

Run terminal-status enum:
- `run_succeeded`
- `run_failed`
- `run_blocked`
- `run_escalated`
- `run_cancelled`

Run aggregation rule:
- `run_succeeded` only if all required plan tasks reach `task_succeeded`
- `run_failed` if any required task reaches `task_failed` and no higher-priority terminal status applies
- `run_blocked` if a required task reaches `task_blocked`
- `run_escalated` if a required task reaches `task_escalated`
- `run_cancelled` on explicit user/operator cancellation

Compact control-plane transition table:

| Current state | Trigger | Persisted artifacts | Next state | Terminal? |
| --- | --- | --- | --- | --- |
| `intake` | submission accepted | run manifest, intake event | `planning` | no |
| `planning` | plan valid | `plan.json`, validation record | `dispatch_ready` | no |
| `planning` | ambiguity requires human input | ambiguity report | `run_escalated` | yes |
| `dispatch_ready` | task selected + packet built | `ExecutionPacket` | `executing` | no |
| `executing` | backend attempt returned | `AttemptResult`, raw output, artifacts | `evaluating` | no |
| `evaluating` | recommendation=`repair` and budget remains | failure packet, strategy update | `dispatch_ready` | no |
| `evaluating` | recommendation=`debug` and budget remains | debug brief / evidence refs | `dispatch_ready` | no |
| `evaluating` | recommendation=`review` | reviewer packet / validator request | `reviewing` | no |
| `reviewing` | review passed | review report | `task_succeeded` | yes |
| `reviewing` | review rejected but retry allowed | review report, rejection-ledger update | `dispatch_ready` | no |
| `evaluating` or `reviewing` | recommendation=`accept` and required validators passed | validator report, execution summary | `task_succeeded` | yes |
| `evaluating` or `reviewing` | recommendation=`block` | blocker packet | `task_blocked` | yes |
| `evaluating` or `reviewing` | recommendation=`escalate` | escalation packet | `task_escalated` | yes |
| any non-terminal | explicit stop / budget exhausted | stop event / budget record | `task_cancelled` or `task_failed` | yes |

Hard rules:
- `accept` is illegal unless all required validators have passed and any required review gate has passed
- `repair` and `debug` are illegal if they would replay a rejected strategy without a recorded `required_delta_for_retry`
- only the control plane may derive run-level terminal status from task-level terminals

### 6.6 Prompt / audit record

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

Prompt persistence and replay policy:
- Always persist the full rendered prompt text when it is short enough and safe to store directly. The stored artifact is the normative replay record for that attempt.
- If the rendered prompt includes large repo excerpts, generated evidence blobs, or sensitive material that policy says must not be duplicated into the manifest, persist:
  - the prompt template/policy version
  - packet/evidence/file refs used to render it
  - a stable `instructions_hash` of the exact rendered prompt
  - an optional encrypted or access-controlled prompt blob ref when available
- Never require the run manifest itself to hold giant prompt bodies. Store bulky material in artifact files and reference them.
- Replay expectation: Crucible must support either exact replay from the stored rendered prompt or deterministic reconstruction from the stored refs + hashes. If deterministic reconstruction is not possible, the exact rendered prompt blob must be persisted.
- Privacy boundary: hashes/refs alone are insufficient if they cannot prove what the model saw during audit. For high-risk attempts, store the exact rendered prompt in an access-controlled artifact even if the manifest only stores a ref + hash.

### 6.7 Strategy memory / rejection ledger

Purpose: prevent repeated bad retries and persist semantic learning within a run.

Bugfix protocol semantics:
- Canonical bugfix states: `investigating` -> `reproduced` -> `fixing` -> `verifying` -> `verified`
- Allowed exceptional states: `reproduction_not_possible`, `blocked`, `escalated`
- Normal rule: a bugfix task should not enter `fixing` until `reproduced` has durable evidence

What counts as reproduction evidence:
- a failing targeted test added or identified and shown failing before the fix
- a deterministic command/script that reproduces the bug and emits the failing symptom
- a durable artifact proving the pre-fix failure, such as stack trace, assertion output, screenshot, or log excerpt tied to the exact workspace/revision

When reproduction is not possible:
- allowed only if the failure is nondeterministic, environment-dependent, externally unavailable, or already disappeared on current head
- the attempt must persist a `reproduction_not_possible` record containing:
  - why reproduction could not be achieved
  - what reproduction approaches were tried
  - what surrogate evidence justified proceeding
  - what post-fix validation was used instead
- if reproduction is not possible and post-fix validation still fails, the task must transition to `task_failed`, `task_blocked`, or `task_escalated`; it may not claim success on narrative confidence alone

Compact bugfix transition table:

| Current bugfix state | Trigger | Persisted artifacts | Next state | Terminal? |
| --- | --- | --- | --- | --- |
| `investigating` | failure mechanism understood + reproduce evidence captured | failing test/log/screenshot refs | `reproduced` | no |
| `investigating` | reproduction impossible but justified | `reproduction_not_possible` record | `reproduction_not_possible` | no |
| `reproduced` | fix attempt begins | attempt brief, strategy entry | `fixing` | no |
| `reproduction_not_possible` | policy allows surrogate validation path | surrogate-validation plan | `fixing` | no |
| `fixing` | patch/evidence generated | diff, attempt result | `verifying` | no |
| `verifying` | required validators pass | validator report | `verified` | yes |
| `verifying` | validators fail and retry allowed | failure packet, rejection-ledger update | `investigating` or `reproduced` | no |
| any non-terminal | unsatisfied prerequisite / external dependency | blocker packet | `blocked` | yes |
| any non-terminal | human decision required | escalation packet | `escalated` | yes |


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

### 7.6 Backend normalization appendix

This appendix is the minimum backend contract for OpenClaw, Claude Code, and Codex CLI. The backend may internally perform many tool/model steps, but Crucible only recognizes a backend invocation as complete when one normalized `AttemptResult` has been emitted and durably stored.

Minimum normalized per-attempt fields required from every backend:
- attempt identity: `attempt_id`, `run_id`, `task_id`, `attempt_index`, `attempt_type`, `backend`
- lifecycle: `status`, `started_at`, `finished_at`, `duration_seconds`
- work summary: `summary`, `files_touched`, `commands_run`, `exit_code`
- evidence: `evidence_refs`, `raw_output_ref`
- model/backend metadata: provider/backend name, model if applicable, `performed_internal_multistep_reasoning`, `performed_file_mutation`, `performed_command_execution`, internal step count if known
- recommendation: one control-plane action enum value

Backend-specific notes:

**OpenClaw**
- May arrive through `src/crucible/runtime/openclaw_tool.py` and bridge-backed execution plumbing.
- If OpenClaw spawns a sub-agent or bridged worker, the spawn/wait transcript refs and any worker-produced artifact refs must be folded into the single normalized `AttemptResult`.
- OpenClaw-native session IDs are embedding metadata only; they are never a substitute for Crucible attempt IDs.

**Claude Code**
- May perform internal tool-use loops, but Crucible still sees one attempt unless Crucible itself explicitly asks for multiple attempts.
- Claude Code must surface the final files touched, commands run, raw transcript/response ref, and model identity for the attempt.
- Hidden chain-of-thought is not required; observable action/evidence outputs are required.

**Codex CLI**
- Same normalization rule as Claude Code: native multi-step behavior is allowed inside one backend attempt, but final persistence must collapse to one canonical `AttemptResult`.
- Codex CLI must report actual command executions and file mutations, not only narrative summaries.
- If Codex cannot provide a field natively, the adapter must synthesize the canonical field from observable artifacts or mark it explicitly unavailable; silent omission is not allowed.

Authority rule:
- backends may sub-loop internally
- adapters normalize the backend transcript into one `AttemptResult`
- the control plane remains the only owner of retry counts, attempt boundaries, and terminal classification

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
- reproduction evidence rules are enforced for bugfix tasks

### Exit criteria
- bug-fix tasks have explicit protocol state
- retry semantics use semantic memory, not only raw logs
- bugfix tasks persist reproduction evidence or a durably justified non-reproducible decision

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
