# OpenClaw entry: Crucible as the durable execution substrate

Phase 5 makes the OpenClaw front door explicit.

## Stable embedding API

Import from `crucible.runtime`:

- `openclaw_run(payload)`
- `openclaw_status(payload)`
- `openclaw_watch(payload)`
- `openclaw_resume(payload)`
- `openclaw_lint(payload)`
- `openclaw_execute(payload)` for the generic mode-switched wrapper
- `TOOL_SCHEMA` for host-side tool registration

These helpers are thin wrappers over the same durable runtime truth used by the CLI-backed OpenClaw tool wrapper in `src/crucible/runtime/openclaw_tool.py`.

## Input contract

Common payload fields:

- `plan` for `run` / `lint`
- `run_id` for `status` / `watch` / `resume`
- `runs_dir` to pin the durable run root
- `workspace_root` to pin execution workspace
- `embedding_surface` to identify the OpenClaw UX surface (for example `telegram-topic`, `openclaw-mobile`, `openclaw-desktop`)
- `embedding_session_ref` to preserve the host session/thread reference
- `openclaw_spawn_callable` + `openclaw_wait_callable` when the embedder wants execution to run underneath OpenClaw rather than the plain CLI shell path

## Durable semantics guarantee

OpenClaw submit/status/watch/resume all map to the same run manifest, durable `plan.json`, attempts, and result summary.

Terminal run summaries now use canonical run enums (`run_succeeded`, `run_failed`, `run_blocked`, `run_escalated`, `run_cancelled`). `result.json` also carries `legacy_terminal_status` for downgrade compatibility with older readers.

That means:

- `run_id` is the durable identity, not any OpenClaw session id
- `run_root` is stable across `run` and `resume`
- `status` and `watch` inspect the same persisted plan/result artifacts created during `run`
- `embedding_surface` and `embedding_session_ref` are embedding metadata only; they do not replace Crucible run identity
- changing the OpenClaw surface used to inspect a run must not change runtime truth

## Durable artifact layout you should expect

A successful or failed OpenClaw-submitted run is inspectable through the same artifact layout as the CLI path:

- `run.json`
- `tasks.json`
- `plan.json`
- `events.jsonl`
- `result.json`
- `attempts/<attempt_id>.json`
- `artifacts/<task_id>/repo_summary.json`
- `artifacts/<task_id>/strategy-memory.json`
- `artifacts/<task_id>/prompt-audit-*.json`
- `artifacts/<task_id>/validator-chain-*.json`
- `evidence/<task_id>/*`
- `workspaces/<task-attempt>/`

This was re-verified in Phase 6 against the current shipped runtime.

## Normalized adapter boundary

When OpenClaw execution is supplied through `openclaw_spawn_callable` and `openclaw_wait_callable`:

- Crucible normalizes the backend through `SessionsSpawnBridge` and `BridgeBackedAdapter`
- adapter state is persisted under the run root
- OpenClaw-native session ids are stored as adapter metadata only
- Crucible remains the owner of attempt boundaries, durable artifacts, and terminal result classification

## Intended usage

- Use `openclaw_run()` when OpenClaw is submitting a software task.
- Use `openclaw_status()` for point-in-time state.
- Use `openclaw_watch()` for event/timeline inspection.
- Use `openclaw_resume()` to continue or re-read a durable run after interruption.

The UX can differ by OpenClaw surface. The runtime truth must not.
