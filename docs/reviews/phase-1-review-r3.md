# Phase 1 review r3 against `docs/crucible-spec-v7.3.2.md`

## Verdict
SHIP

## Scope reviewed
- `docs/crucible-spec-v7.3.2.md` (Phase 1 + release gates)
- `docs/reviews/phase-1-review-r2.md`
- `src/crucible/planning/plan.py`
- `src/crucible/runtime/run_store.py`
- `src/crucible/runtime/cli.py`
- `src/crucible/runtime/openclaw_tool.py`
- `src/crucible/runtime/run_executor.py`
- `tests/runtime/test_cli.py`
- `tests/runtime/test_openclaw_tool.py`
- `tests/runtime/test_run_store.py`
- targeted adversarial repro of ambiguous plan submission

## What I re-checked from r2

### 1) Previous blocker: ambiguous runs leaving a validated `plan.json`
Status: **fixed**.

What changed:
- `create_run_store(..., persist_validated_plan=False)` is now used in both runtime entry paths:
  - CLI `cmd_run()`
  - OpenClaw tool `_do_run()` bridge/direct path
- Ambiguity detection now runs **before** `build_plan_artifact()` / `write_plan()` in those entry paths.
- New tests cover both surfaces:
  - `tests/runtime/test_cli.py::test_ambiguous_run_does_not_persist_validated_plan`
  - `tests/runtime/test_openclaw_tool.py::test_ambiguous_run_does_not_leave_validated_plan`

I also repro’d this manually/adversarially with a plan containing `todo` and `decide later`:
- exit code was `3` as expected
- run manifest ended in `current_status = escalated`
- only `run.json`, `tasks.json`, and `events.jsonl` existed
- **no `plan.json` was written**
- manifest `plan_status` remained `missing`

That closes the contradiction called out in r2.

### 2) Hard gate on execution without validated durable plan
Status: **still fixed**.

Evidence:
- `execute_run()` begins with `ensure_validated_plan(store.read_plan())`
- on failure it emits `plan_gate_failed` and terminates failed
- tests still cover:
  - initial execution fail-closed if `plan.json` is deleted before execute
  - resume rejects missing durable `plan.json`

### 3) Plan-state visibility on status/watch/resume
Status: **fixed and adequate for Phase 1**.

Evidence:
- `status` returns `plan`, `plan_present`, `plan_status`, `plan_path`
- `watch` emits initial `plan_state`
- OpenClaw wrapper mirrors plan visibility for `status/watch/resume`

## Phase-1 gate assessment vs 7.3.2

### Passes
- invalid/missing plan is rejected before execution
- validated plan is durably persisted on disk for non-ambiguous runs
- task entries in `plan.json` contain:
  - `dependencies`
  - `acceptance_criteria`
  - `validation_policy`
  - `review_policy`
- `status/watch/resume` expose plan state and artifact location
- CLI and OpenClaw front doors both honor the same plan-gate behavior

### Remaining caveats (not Phase-1 blockers)
- `create_run_store()` still defaults `persist_validated_plan=True`. A low-level caller could misuse that helper and recreate the old ambiguity-order bug outside the shipped entry paths. I do **not** consider this a Phase 1 blocker because the spec gate is about the runtime entry path and the reviewed front doors are fixed, but it is worth tightening later if `create_run_store()` is treated as public embedding API.
- `manifest.plan_ref` is populated with the canonical future path even when no plan file exists yet. That is acceptable given `plan_present` / `plan_status` are the real truth fields, but callers must not treat `plan_ref` alone as existence proof.

## Test run
Ran:
- `.venv/bin/python -m pytest -q tests/runtime/test_cli.py tests/runtime/test_openclaw_tool.py tests/runtime/test_run_store.py`

Result:
- `56 passed`

## Recommendation
- **Advance to Phase 2**
- I do not see a remaining Phase-1 release-gate blocker under `docs/crucible-spec-v7.3.2.md`.
