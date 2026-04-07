# Crucible Architecture

This document explains how Crucible is structured, what each subsystem is responsible for, and how the runtime fits into an OpenClaw-style chat surface.

## One-line summary

Crucible is a **deterministic execution runtime** for long-running software tasks.

It takes work that would normally be left to chat continuation — retrying after failure, choosing the next repair action, tracking evidence, managing workspaces, resuming runs, and surfacing truthful status — and moves that responsibility into code.

## Design goal

The core design goal is:

> once a task enters the runtime, Crucible — not incidental chat history — should own task closure.

That means the runtime should be responsible for:
- attempt creation
- validation
- failure classification
- next-action selection
- workspace lineage
- repair / debug / review handoffs
- durable state and evidence
- resume / watch / status surfaces

## High-level model

Crucible sits between:
- an **embedding interface** (for example OpenClaw), and
- the **workers / backends / tool executions** that actually do the work.

```text
User / Chat Surface
        │
        ▼
OpenClaw / Skill Layer
- user intent
- task intake
- UX / messaging
        │
        ▼
Crucible Runtime
- attempts
- validation
- evidence
- deterministic next action
- closure loop
- durable run state
        │
        ▼
Workers / Backends / Commands
- builder
- reviewer
- debugger
- salvage/integration paths
```

## Runtime responsibilities

At runtime, Crucible is supposed to answer questions like:
- What attempt are we on?
- What failed?
- What evidence do we have?
- Is this a repair, debug, review, salvage, integration, or revalidation step?
- Which workspace should the next attempt use?
- What is the next deterministic action?
- Is the run complete, blocked, partial, awaiting user input, or still progressing?

Those answers should come from persisted runtime state, not a chat model re-inventing them.

## Main subsystems

### 1. `state/`
Core typed runtime contracts.

Important concepts here include:
- attempt states
- attempt types
- workspace records
- runtime-owned state primitives

This layer defines the vocabulary the rest of the system uses.

### 2. `failures/`
Failure taxonomy and next-step policy.

Key jobs:
- classify what kind of failure happened
- persist structured failure evidence
- choose the next action deterministically

This is where Crucible moves from “something went wrong” to “here is exactly what the runtime should do next.”

### 3. `policy/`
Budgets and circuit breaking.

This layer decides:
- how many attempts are allowed
- when retries are exhausted
- when the runtime should stop looping
- when repeated failures indicate a deeper issue

It prevents infinite or vague retry behavior.

### 4. `runner/`
Role and handoff logic.

This layer encodes the relationships between:
- builder
- reviewer
- debugger
- salvage
- integrator

It also enforces the non-identical retry rule so the runtime does not blindly respawn the same failed shape repeatedly.

### 5. `workspace/`
Workspace lineage and workspace management.

Crucible tracks whether an attempt uses:
- a fresh workspace
- a repair basis
- a salvage path
- inherited or replayed artifacts

This matters because retries are not interchangeable: the runtime should know whether an attempt is starting clean or building on prior work.

### 6. `evidence/`
Durable evidence manifests and evidence storage.

This layer stores:
- failure packets
- validation outputs
- logs
- artifacts
- criterion results
- manifests tied to attempts

The goal is that every important runtime claim can be backed by persisted evidence.

### 7. `orchestrator/`
Closed-loop execution semantics.

This is the heart of v5.4-style behavior.

Key components:
- `closed_loop_executor.py`
- `task_state_machine.py`
- `run_closure.py`

This layer owns the runtime loop:
- build
- validate
- fail honestly
- choose next action
- repair/debug/review/integrate as needed
- continue until terminal state

### 8. `runtime/`
The live runtime surface exposed to the embedding system.

Important files include:
- `run_executor.py`
- `run_store.py`
- `openclaw_tool.py`
- `resume_handler.py`
- `status_emitter.py`
- `cli.py`

This layer is the bridge between the abstract runtime model and actual runs on disk / tool calls / status commands / resume behavior.

### 9. `validation/`
Validation and review infrastructure.

This layer is about making sure the runtime does not claim progress without evidence.

### 10. `integration/`
Fan-in and merged-output semantics.

This matters when multiple outputs or partial results need to be combined and then revalidated.

### 11. `workflows/`
Higher-level workflows on top of the runtime.

These are more task-shaping / workflow-facing than core closure semantics.

## Core runtime loop

A simplified v5.4-style loop looks like this:

```text
queued
  -> build attempt
  -> validation
     -> pass -> review -> complete
     -> fail -> classify failure
              -> repair
              -> debug
              -> salvage
              -> awaiting_user
              -> blocked
```

The important property is not that every task follows the same path.

The important property is that:
- the path is explicit
- the next step is chosen by runtime policy
- the decision is inspectable
- the state is durable

## Typed attempts

A major architectural choice in v5.4 is that retries are **typed**, not generic.

Examples:
- `build`
- `repair`
- `debug`
- `review`
- `salvage`
- `integrate`
- `revalidate`

That lets the runtime answer not just “we tried again,” but:
- what kind of attempt was this?
- why did we schedule it?
- what evidence justified it?
- what should happen if it fails again?

## Durable attempt lineage

Crucible tracks attempts durably so you can inspect:
- what happened first
- which attempt derived from which other one
- which workspace was used
- what evidence existed
- what next action was chosen
- which attempt superseded another

This is critical for both debugging and truthful UX.

## Review is a real gate

Review should not be just narration.

Architecturally, review is important because it provides a distinct runtime gate after implementation/repair work. A task should not move to complete merely because a worker said it was fixed.

A review step should be able to:
- accept
- reject
- escalate

And the runtime should react deterministically.

## Failure classification

Crucible tries to be structured-first rather than heuristic-first.

That means the runtime should prefer:
- structured failure artifacts
- observed state
- persisted signatures
- known failure classes

over ad hoc string matching or casual interpretation.

## OpenClaw integration model

OpenClaw is the conversational / tool surface.
Crucible is the execution substrate.

A typical interaction looks like:

1. OpenClaw receives a user request
2. OpenClaw skill/tooling converts it into a task/run request
3. Crucible executes and persists the runtime state
4. OpenClaw exposes:
   - start
   - watch
   - status
   - resume
   - final result

This separation is important:
- OpenClaw owns user interaction
- Crucible owns execution semantics

## Why this architecture exists

Without a runtime like this, long-running coding flows tend to collapse into:
- one-shot execution
- vague retries
- non-durable reasoning
- optimistic status reporting
- failure recovery that depends on chat continuation

Crucible exists to replace that with a system that is:
- durable
- inspectable
- deterministic where it matters
- honest about failure
- resumable

## Where to start reading the code

If you are new to the repo, this is the best path:

1. `README.md`
2. `docs/crucible-spec-v5.4.md`
3. `src/crucible/runtime/run_executor.py`
4. `src/crucible/orchestrator/closed_loop_executor.py`
5. `src/crucible/orchestrator/task_state_machine.py`
6. `src/crucible/failures/next_action_selector.py`
7. `src/crucible/runtime/run_store.py`
8. `tests/runtime/test_closed_loop_runtime_e2e.py`

## Current limitations / future cleanup

Even with the current v5.4 work, there is still normal engineering cleanup that may happen later:
- further splitting large runtime helpers into smaller units
- making telemetry even cleaner for special lanes like environment-fix
- deepening integration/post-integration invariants further
- expanding more true end-to-end scenarios

Those are refinement tasks, not a change in the fundamental architecture.

## Summary

Crucible is best understood as:

> a deterministic, evidence-backed runtime for chat-native software execution.

If OpenClaw is the conversation layer, Crucible is the part that makes the work loop real.