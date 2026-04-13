# Crucible Architecture

This document describes the shipped architecture on the `docs/crucible-spec-v7.3.2.md` line.

## One-line summary

Crucible is a library-first durable execution substrate for software tasks.

OpenClaw is the primary user-facing front door. Crucible owns the durable runtime truth underneath it.

## Current architectural split

Crucible is implemented as two nested layers:

- Control plane
  - intake / plan validation
  - task ordering
  - policy selection
  - packet construction
  - next-action transitions
  - durable run state
- Execution core
  - task-local context
  - prompt instantiation
  - backend execution
  - evidence collection
  - structured execution results

Hard boundary:
- OpenClaw may submit, inspect, watch, and resume runs
- Crucible owns run identity, plan truth, attempt boundaries, evidence, and terminal classification

## Main shipped subsystems

- `planning/`
  - durable plan normalization and validation
- `runtime/`
  - run entrypoints, run store, status/watch/resume, OpenClaw wrapper, execution loop
- `environment/`
  - existing-repo detection and provisioning
- `failures/`
  - failure packets and next-action selection
- `policy/`
  - retry budgets and circuit breaking
- `workspace/`
  - workspace lineage / per-attempt workspaces
- `validation/`
  - validators, reviewer surfaces, anti-vacuity checks
- `orchestrator/`
  - closed-loop attempt semantics used by the runtime layer

## Durable run layout observed from shipped code

A real runtime run currently persists:

- `run.json`
  - run manifest
- `tasks.json`
  - normalized task snapshot
- `plan.json`
  - durable validated plan artifact
- `events.jsonl`
  - append-only run timeline
- `result.json`
  - final run summary
- `attempts/<attempt_id>.json`
  - per-attempt durable records
- `artifacts/<task_id>/repo_summary.json`
- `artifacts/<task_id>/strategy-memory.json`
- `artifacts/<task_id>/prompt-audit-*.json`
- `artifacts/<task_id>/validator-chain-*.json`
- `artifacts/<task_id>/reproduction-not-possible-*.json` when a bugfix uses justified surrogate validation instead of a literal reproduction
- `evidence/<task_id>/*`
  - manifests / failure evidence
- `workspaces/<task-attempt>/`
  - per-attempt workspace copies
- `adapter.log`
  - backend/adapter trace

This layout was verified again in a real tiny Phase 6 runtime run on 2026-04-12.

Run/task terminal classification now persists canonical terminal enums end-to-end:
- task terminals: `task_succeeded`, `task_failed`, `task_blocked`, `task_escalated`, `task_cancelled`
- run terminals: `run_succeeded`, `run_failed`, `run_blocked`, `run_escalated`, `run_cancelled`
- `result.json` also includes `legacy_terminal_status` so older consumers can still read the final outcome safely.

## Execution packet and attempt truth

The runtime no longer treats the verification command as the entire task description.

Current behavior:
- `run_executor.py` builds a task-aware prompt from the `ExecutionPacket`
- backend execution commands live in structured adapter metadata (`metadata["command"]`)
- `LocalShellAdapter` remains an honest shell-execution baseline
- agentic/OpenClaw-backed execution can consume the task-aware prompt while still preserving normalized attempt records

So the honest claim is:
- the default local-shell backend is a validation baseline
- the runtime itself now persists task-aware packet/audit/strategy artifacts
- benchmark solving claims should only be made for backends that can actually edit code, not for the plain shell baseline

## Environment hardening contract

Environment provisioning is now considered successful only when the runtime can prove the expected validation surface is runnable.

Current shipped checks:
- Python repos require a real `.venv` with a Python executable
- repos that imply installation work (`pyproject.toml` or non-empty `requirements.txt`) must also show install completion
- when the detected Python test tool is `pytest`, Crucible now runs:
  - `.venv/bin/python -m pytest --version`
- failed readiness checks are persisted in `.crucible/environment.json` as:
  - `readiness_checks`
  - `readiness_failures`
  - `failure_reason`
  - `failure_class`

This prevents the old over-claim where provisioning could say `provisioned` even though the selected test surface was not runnable.

## OpenClaw front door

Use the stable embedding helpers from `crucible.runtime`:

- `openclaw_run`
- `openclaw_status`
- `openclaw_watch`
- `openclaw_resume`
- `openclaw_lint`
- `openclaw_execute`
- `TOOL_SCHEMA`

These helpers map to the same run store and artifact layout as the CLI.

## Honest benchmark posture

What Crucible can now honestly claim for benchmark-style runs:

- durable validated plans exist on disk
- task-aware execution packets exist on disk
- strategy memory and prompt/audit artifacts exist on disk
- OpenClaw and CLI inspect the same durable run truth
- environment failures are surfaced as concrete runnable-surface failures instead of false provisioning success

What Crucible should not over-claim:

- the plain `local-shell` backend is not a code-editing solver
- a benchmark failure on the local-shell backend is still a backend limitation unless a real editing backend is supplied

## Suggested reading order

1. `docs/crucible-spec-v7.3.2.md`
2. `docs/openclaw-entry.md`
3. `src/crucible/runtime/run_executor.py`
4. `src/crucible/runtime/run_store.py`
5. `src/crucible/environment/existing_repo.py`
6. `tests/runtime/test_execution_packet_phase2.py`
7. `tests/runtime/test_phase3_bugfix_protocol.py`
8. `tests/runtime/test_phase4_audit_policy.py`
9. `tests/runtime/test_phase5_openclaw_frontdoor.py`
10. `tests/environment/test_existing_repo.py`
