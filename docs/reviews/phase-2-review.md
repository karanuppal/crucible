# Phase 2 review against crucible-spec-v7.3.2

Date: 2026-04-11
Reviewer stance: adversarial / release-gate focused

## Scope reviewed
Only Phase 2 requirements/gates from `docs/crucible-spec-v7.3.2.md`.

Files inspected:
- `docs/crucible-spec-v7.3.2.md`
- `src/crucible/runtime/execution_models.py`
- `src/crucible/runtime/run_executor.py`
- `src/crucible/runtime/local_shell_adapter.py`
- `src/crucible/runtime/__init__.py`
- `tests/runtime/test_execution_packet_phase2.py`
- `tests/runtime/test_local_shell_adapter.py`
- `tests/runtime/test_closed_loop_runtime_e2e.py`
- `docs/implementation/phase-2-build-notes.md`

## Test check
Command run:
- `uv run pytest -q tests/runtime/test_execution_packet_phase2.py tests/runtime/test_local_shell_adapter.py tests/runtime/test_closed_loop_runtime_e2e.py`

Result:
- 21 passed
- warnings only (budget_tracker uses deprecated `datetime.utcnow()`)

## Phase 2 requirements from spec
Build:
- `ExecutionPacket` model + serializer
- repo summary / relevant-files extractor
- packet builder from plan + run state
- migration away from verification-command-as-primary-worker-prompt in default solving path
- structured execution result object

Tests required:
- packet contains repo context + policy snapshot + prior evidence refs
- task-aware backend path can run from packet
- default path no longer depends solely on shell command prompt wiring

Exit criteria:
- execution core receives packets, not only bare verification commands
- retries consume prior evidence and strategy refs
- local shell remains validation baseline, not the primary architecture claim

Release gate:
- code exists
- tests prove behavior
- disk artifacts are inspectable
- docs match shipped behavior
- no “task-aware execution” claim until `ExecutionPacket` is real and used

## What is solid
- `ExecutionPacket` exists as a real dataclass with serializer.
- Packet construction is wired into real runtime execution and review paths (`run_executor.py`).
- Attempt metadata persists `execution_packet` and `structured_execution_result`, so there is durable on-disk evidence through run-store attempt records.
- Default path no longer relies only on `AdapterRunSpec.prompt`; executor puts task-aware instructions in `prompt` and shell command in `metadata["command"]`.
- `LocalShellAdapter` honors `metadata["command"]` and still acts as honest shell-validation baseline.
- Tests directly cover the new packet path and command override behavior.

## What is incomplete / weak
### 1) Phase 2 exit criterion on strategy refs is not truly met
Spec says: `retries consume prior evidence and strategy refs` and §6.2 says every retry can reference prior failure evidence and strategy memory.

Reality:
- prior evidence refs are passed
- `strategy_memory_ref` is hardcoded to `None` in both execution and review packet builds

This is the biggest gap. The build notes admit it is deferred to Phase 3, but the Phase 2 exit criteria in 7.3.2 still claim strategy refs as part of completion.

### 2) Repo summary is lightweight and not durable as a first-class artifact
Spec example shows `repo_summary_ref`; implementation only embeds a tiny inline summary plus relevant file list. No durable repo-summary artifact is written.

This is probably acceptable for a minimum Phase 2 if the claim is “task-aware packet exists,” but not if someone interprets the packet contract literally.

### 3) Docs are slightly self-contradictory
Spec §2.3 says LocalShellAdapter still treats `AdapterRunSpec.prompt` as the command to run. Current code no longer does that first; it prefers `metadata["command"]` and only falls back to `prompt`.

The Phase 2 section and build notes match the code, but the earlier “honest current default path” text is stale. That weakens the release-gate requirement that docs match shipped behavior.

### 4) Policy snapshot is still mostly synthetic/defaulted
`prompt_family`, `model_route`, `attempt_budget`, and `tool_scope` are generated defaults rather than a real control-plane-selected policy snapshot. This is good enough for a Phase 2 skeleton, but should not be oversold as fully policy-managed execution.

## Verdict
NEEDS FIXES

## Why not SHIP
If Phase 2 is judged strictly against 7.3.2, the strategy-ref exit criterion is not met, and docs are not perfectly aligned with shipped behavior. The implementation is close and the tests pass, but it is not cleanly “complete” by the written gate.

## Should we advance to Phase 3?
Not yet. Do a short Phase-2.1 cleanup first so Phase 3 starts from honest ground.

## Top fixes required
1. Resolve the strategy-ref gate mismatch:
   - either implement a minimal durable `strategy_memory_ref` artifact now, even if empty/bootstrap-only, and thread it through retries
   - or explicitly amend the spec/build notes so strategy memory is Phase 3-only and remove it from Phase 2 exit criteria
2. Fix the stale doc text in §2.3 about LocalShellAdapter using `prompt` as the command.
3. Consider persisting a small `repo_summary.json` artifact and referencing it from `repo_context` if you want the packet contract to match the spec more literally.

## Bottom line
The code meaningfully delivers a real Phase 2 packet path. But under a strict reading of v7.3.2, it is not fully shippable yet because one of the named exit criteria is still knowingly unimplemented.