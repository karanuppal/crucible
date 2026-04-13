# Phase 2 re-review against crucible-spec-v7.3.2

Date: 2026-04-11
Reviewer stance: adversarial / release-gate focused

## Scope reviewed
Only Phase 2 requirements and release gates from `docs/crucible-spec-v7.3.2.md`.

Files inspected:
- `docs/crucible-spec-v7.3.2.md` (Phase 2 + release gates)
- `docs/reviews/phase-2-review.md`
- `src/crucible/runtime/execution_models.py`
- `src/crucible/runtime/run_executor.py`
- `src/crucible/runtime/local_shell_adapter.py`
- `tests/runtime/test_execution_packet_phase2.py`
- `tests/runtime/test_local_shell_adapter.py`
- `tests/runtime/test_closed_loop_runtime_e2e.py`
- `docs/implementation/phase-2-build-notes.md`

## Test check
Command run:
- `uv run pytest -q tests/runtime/test_execution_packet_phase2.py tests/runtime/test_local_shell_adapter.py tests/runtime/test_closed_loop_runtime_e2e.py`

Result:
- `22 passed`
- warnings only, unrelated to Phase 2 gate (`datetime.utcnow()` deprecation in `budget_tracker.py`)

## Phase 2 gate summary
Spec requires:
- real `ExecutionPacket`
- repo summary / relevant-files extractor
- packet builder from plan + run state
- default path no longer centered on bare verification command prompt wiring
- structured execution result object

Tests/gates require:
- packet includes repo context + policy snapshot + prior evidence refs
- task-aware backend path runs from packet
- retries consume prior evidence and strategy refs
- local shell stays validation baseline, not architectural overclaim
- code exists, tests prove behavior, disk artifacts are inspectable, docs match shipped behavior

## Previous findings re-check
### 1) Strategy refs missing in retries
Previous finding: `strategy_memory_ref` was effectively unimplemented.

Current state:
- fixed for Phase 2 gate purposes
- `ensure_strategy_memory_artifact()` persists `artifacts/<task_id>/strategy-memory.json`
- execution and review packet builders thread the resulting ref into `history.strategy_memory_ref`
- tests now assert the artifact exists on disk and the ref is present

Adversarial note:
- this is only a bootstrap artifact, not true Phase 3 semantic strategy memory/rejection-ledger behavior
- but that is acceptable for Phase 2 because the gate language asks for strategy refs to be consumed, not full Phase 3 semantics

### 2) Repo summary not durable
Previous finding: repo summary existed only inline.

Current state:
- fixed
- `persist_repo_summary_artifact()` writes `artifacts/<task_id>/repo_summary.json`
- packet `repo_context` includes `repo_summary_ref`
- tests assert the artifact exists and contains expected relevant files

### 3) Docs stale about LocalShellAdapter command source
Previous finding: docs still suggested prompt-first command execution.

Current state:
- fixed in the implementation-facing docs reviewed here
- `local_shell_adapter.py` docstring now correctly states Phase 2 behavior: execute `metadata["command"]` first, fall back to `prompt`
- `phase-2-build-notes.md` matches shipped behavior

Caveat:
- the broader spec still contains historical explanatory text in §2.3, but that is spec-level background, not the implementation notes for this phase. I do not think it blocks Phase 2 release.

### 4) Policy snapshot was synthetic/defaulted
Previous finding: policy snapshot was mostly synthetic.

Current state:
- still true, but not a Phase 2 blocker
- Phase 2 requires a policy snapshot in the packet, not a fully mature prompt-policy system
- Phase 4 is where stronger policy/audit semantics become mandatory

## New issues found
No new Phase-2-blocking issues found.

## Verdict
SHIP

## Why
Under the 7.3.2 Phase 2 gate language, this now clears review:
- code exists
- tests prove behavior
- packet path is real and used in runtime execution/review flows
- on-disk artifacts are inspectable (`repo_summary.json`, `strategy-memory.json`, attempt metadata with `execution_packet` and `structured_execution_result`)
- default path no longer depends solely on shell-command prompt wiring
- local shell remains an honest validation baseline, not the primary architecture claim

## Should we advance to Phase 3?
Yes.

## Watch-outs for Phase 3
- Do not overclaim the bootstrap `strategy-memory.json`; Phase 3 still needs actual rejection-ledger semantics and enforcement.
- The policy snapshot is still placeholder-ish; keep Phase 4 work clearly separated.
- The `datetime.utcnow()` warning is worth cleaning up, but it is not part of this review decision.
