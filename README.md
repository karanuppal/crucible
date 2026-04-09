# Crucible

Crucible is a deterministic runtime for long-running, chat-native software execution.

It is designed to sit underneath an interface like **OpenClaw** and own the parts that must be reliable:
- typed attempts
- workspace lineage
- evidence-backed validation
- deterministic next-action selection
- durable run storage
- build → fail → repair → retest → review loops

In plain English: you point Crucible at a software task, and it keeps pushing the task forward through a structured runtime instead of relying on ad hoc chat continuation.

## Current Status

**Status:** v6.1 runtime implemented and test-backed  
**Branch:** `phase8-production-runtime`  
**Latest local verification:** `728 passed`

What is in the repo now:
- v5.2 / v5.3 / v5.4 design docs plus v6 / v6.1 follow-on specs
- deterministic runtime primitives
- OpenClaw-facing runtime surface
- durable typed-attempt storage
- workspace + evidence handling
- thin 4-class control-plane failure model
- evidence/hint-driven recovery and repair-loop infrastructure
- SWE-bench Verified starter setup for real-world evaluation

## What Crucible Is For

Use Crucible when you want:
- a runtime that **does not pretend success**
- real validation and evidence persistence
- deterministic retry / repair policy
- durable state you can inspect or resume
- a clean substrate for an OpenClaw tool or other chat surface

Crucible is **not** a full standalone product UI. It is the execution/runtime layer.

## Repository Layout

```text
src/crucible/
├── accelerators/   # Backend capability/router plumbing
├── ambiguity/      # Ambiguity gating
├── evidence/       # Evidence storage + manifests
├── failures/       # Failure taxonomy, evidence packets, next-action selection
├── integration/    # Fan-in integration primitives
├── ledger/         # Durable event ledger
├── memory/         # Harness-owned memory store
├── orchestrator/   # Closed-loop execution, task state machine, run closure
├── policy/         # Budgets, circuit breaker
├── runner/         # Handoff controller, retry rules, role execution helpers
├── runtime/        # CLI, run store, OpenClaw tool surface, executor, resume/status
├── scheduler/      # Scheduling + machine profile logic
├── state/          # Core state contracts and typed attempt/workspace models
├── validation/     # Validation / review foundation
├── workflows/      # Higher-level workflows
└── workspace/      # Workspace lineage + manager
```

## Key Docs

### Core specs
- `docs/agentic-harness-spec-v5.2.md`
- `docs/crucible-spec-v5.3.md`
- `docs/crucible-spec-v5.4.md`
- `docs/crucible-spec-v6.md`
- `docs/crucible-spec-v6.1.md`
- `docs/architecture.md`

### Plans / implementation history
- `EXECUTION_PLAN.md`
- `docs/execution-plan-v5.4.md`
- `docs/execution-plan-v6.md`
- `docs/execution-plan-v6.1.md`

### Evaluation
- `docs/evals/swebench-verified/README.md`

## Installation

### Prerequisites
- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/) recommended

### Install dependencies

```bash
cd crucible
uv sync --all-extras --dev
```

If you prefer plain pip/venv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest ruff mypy
```

## Running Tests

Full suite:

```bash
uv run pytest -q
```

Selected areas:

```bash
uv run pytest tests/runtime -q
uv run pytest tests/orchestrator -q
uv run pytest tests/failures -q
```

## CLI Usage

Crucible exposes a CLI entrypoint:

```bash
uv run crucible --help
```

If installed into the active environment:

```bash
crucible --help
```

## OpenClaw Integration

Crucible is built to be embedded by OpenClaw rather than replacing it.

Relevant files:
- `src/crucible/runtime/openclaw_tool.py`
- `src/crucible/runtime/run_executor.py`
- `src/crucible/runtime/run_store.py`
- `src/crucible/runtime/resume_handler.py`
- `src/crucible/runtime/status_emitter.py`

### How it fits into OpenClaw

At a high level:
1. OpenClaw receives the user task
2. OpenClaw/skill layer creates or loads a Crucible plan/run
3. Crucible owns execution semantics:
   - attempts
   - validation
   - failure classification
   - next action
   - repair/review loop
4. OpenClaw surfaces status / watch / resume back to chat

### Important note

This repo does **not** include a full OpenClaw deployment. It provides the runtime layer that OpenClaw can call into.

If you are trying to reproduce the exact chat experience, you will need:
- an OpenClaw installation
- a channel/tool surface that invokes Crucible runtime actions
- whatever backend adapters / worker execution path you want the harness to use

## Minimal Developer Workflow

### 1. Install

```bash
uv sync --all-extras --dev
```

### 2. Run tests

```bash
uv run pytest -q
```

### 3. Inspect the runtime path

Start here if you want to understand how the v6.1 loop works:
- `src/crucible/runtime/run_executor.py`
- `src/crucible/orchestrator/closed_loop_executor.py`
- `src/crucible/orchestrator/task_state_machine.py`
- `src/crucible/orchestrator/run_closure.py`
- `src/crucible/failures/next_action_selector.py`
- `src/crucible/runtime/run_store.py`

### 4. Inspect the tests that prove the runtime

Start here for confidence:
- `tests/runtime/test_closed_loop_runtime_e2e.py`
- `tests/runtime/test_failure_classification_v54.py`
- `tests/runner/test_handoff_controller.py`
- `tests/runner/test_role_executor.py`
- `tests/orchestrator/test_closed_loop_executor.py`
- `tests/orchestrator/test_run_closure.py`
- `tests/orchestrator/test_task_state_machine.py`

## Evaluation with SWE-bench Verified

The repo includes a setup-only starter pack for SWE-bench Verified:
- `evals/swebench-verified/mini-pilot.json`
- `evals/swebench-verified/starter-batch.json`
- `docs/evals/swebench-verified/problems/*.md`

See:
- `docs/evals/swebench-verified/README.md`

This pack is intentionally designed so Crucible can own benchmark execution without bundling gold patches or hand-written solutions.

## What “Done” Means in This Repo

Crucible should only claim progress when it has:
- persisted the attempt/run state
- executed validation honestly
- stored evidence
- selected the next action deterministically
- either continued the loop or reached a clear terminal state

That philosophy is the whole point of this project.

## Contributing / Extending

If you want to extend Crucible, the safest pattern is:
1. update the relevant spec/doc first
2. add tests for the intended runtime behavior
3. implement the smallest deterministic slice that satisfies the behavior
4. verify with `uv run pytest -q`

When changing the closure loop, make sure you are not just improving event narration — make sure the runtime behavior itself changed.

## Quick Start for Newcomers

If you just landed here and want to orient quickly:

1. Read `docs/crucible-spec-v6.1.md`
2. Read `docs/execution-plan-v6.1.md`
3. Run `uv sync --all-extras --dev`
4. Run `uv run pytest -q`
5. Read `tests/runtime/test_closed_loop_runtime_e2e.py`
6. Then inspect `src/crucible/runtime/run_executor.py`

That path gets you from “what is this?” to “how does the runtime actually work?” fast.
