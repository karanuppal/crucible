# SWE-bench Verified with Crucible

This directory contains local benchmark inputs for exercising Crucible against real SWE-bench Verified tasks.

## What this folder is

- local task metadata
- local copies of benchmark problem statements
- generated plan inputs for Crucible runs

## What this folder is not

- a hidden benchmark harness
- gold patches
- hand-authored task solutions
- benchmark-specific cheating logic

## Honest current usage

Use this pack to answer two different questions separately:

1. Does Crucible persist truthful runtime artifacts for benchmark-style work?
2. Can the backend underneath Crucible actually solve the task?

Those are not the same question.

Crucible now persists the runtime-side architecture needed for honest benchmark evaluation:
- validated `plan.json`
- task-aware execution packets
- strategy memory
- prompt-audit artifacts
- validator-chain artifacts
- durable attempts/events/results

But the backend still matters:
- `local-shell` is an honest validation baseline, not a code-editing solver
- OpenClaw/agentic backends are the path for genuine code-editing benchmark attempts

So benchmark claims must always name the backend used.

## Phase 6 rerun takeaway

A representative rerun on `astropy__astropy-14309` now fails for a concrete, inspectable reason:

- provisioning no longer reports misleading success
- the run records a failed Python readiness check
- `.crucible/environment.json` captures the exact failed command:
  - `.venv/bin/python -m pytest --version`
- the failure is therefore attributable to a real environment/tooling gap in that workspace, not to missing runtime artifacts or missing plan/audit machinery

See:
- `docs/evals/swebench-verified/v6.1-batch-report.md` for the earlier baseline
- `docs/evals/swebench-verified/v7.3.2-rerun-note.md` for the current Phase 6 rerun note

## Recommended evaluation flow

For a benchmark task:

1. choose a task from `mini-pilot.json` or `starter-batch.json`
2. check out the target repo at the benchmark `base_commit`
3. run Crucible with a named backend expectation
4. inspect the durable artifacts before interpreting the outcome

Interpretation rules:
- if plan / packet / audit / evidence are missing, that is a runtime architecture problem
- if those artifacts exist and the backend cannot edit code, that is a backend capability limitation
- if those artifacts exist and a real editing backend still fails, then the failure may be task difficulty, model quality, or repo-specific complexity

## Current reading order

1. `docs/crucible-spec-v7.3.2.md`
2. `docs/architecture.md`
3. this file
4. `docs/evals/swebench-verified/v7.3.2-rerun-note.md`
5. `tests/environment/test_existing_repo.py`
6. `tests/runtime/test_execution_packet_phase2.py`
