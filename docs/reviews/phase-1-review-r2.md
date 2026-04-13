# Phase 1 review r2 against `docs/crucible-spec-v7.3.2.md`

## Verdict
NEEDS FIXES

## Scope reviewed
- `docs/crucible-spec-v7.3.2.md` (Phase 1 + release gates)
- `docs/reviews/phase-1-review.md`
- `src/crucible/planning/__init__.py`
- `src/crucible/planning/plan.py`
- `src/crucible/runtime/run_executor.py`
- `src/crucible/runtime/run_store.py`
- `src/crucible/runtime/cli.py`
- `src/crucible/runtime/openclaw_tool.py`
- `tests/runtime/test_cli.py`
- `tests/runtime/test_openclaw_tool.py`
- nearby runtime behavior via direct code-path inspection

## Previous findings re-check
1. Runtime-core invariant missing
- Fixed enough at executor level.
- `execute_run()` now hard-gates on `ensure_validated_plan(store.read_plan())` and emits `plan_gate_failed` before returning terminal failed.
- There is also an adversarial CLI test deleting `plan.json` before execution and asserting fail-closed behavior.
- This closes the biggest gap from r1.

2. `create_run_store()` swallowed plan-build exceptions
- Fixed.
- The old `except Exception: pass` behavior is gone.
- `create_run_store()` now raises on planning failure and tests cover that.

3. `watch` did not expose current plan state directly
- Fixed.
- `cmd_watch()` now emits an initial `plan_state` snapshot with `plan_present`, `plan_status`, `plan_path`, and the plan artifact itself.
- Wrapper `watch` also reflects the durable plan state.

4. Docs/version mismatch
- Fixed.
- The reviewed spec file is correctly titled v7.3.2.

5. Hard-gate proof too narrow
- Improved materially.
- There is now a direct test of execution failing closed if `plan.json` is deleted before initial execution.
- Still not exhaustive for every conceivable entrypoint, but enough for Phase 1.

## New issue found
### Ambiguous runs still persist a validated `plan.json`
This is the remaining blocker.

`create_run_store()` writes a validated durable plan immediately from `task_plan`, before ambiguity handling in `cmd_run()` / OpenClaw run mode.

As a result, an ambiguous submission can:
- create `runs/<id>/plan.json` with `status: validated`
- then escalate with manifest `current_status = escalated`
- and leave `manifest.plan_status = missing` while the on-disk durable plan says `validated`

I reproduced this adversarially with a spec containing `todo` / `decide later`:
- CLI exited 3 for ambiguity as expected
- manifest status became `escalated`
- `plan.json` still existed and had `status: validated`
- manifest `plan_status` remained `missing`

Why this matters under 7.3.2 gate language:
- Phase 1 defines planning/ambiguity handling as part of the plan gate.
- A durable `validated` plan artifact should not exist for a run that has already been deemed ambiguous and escalated before execution.
- This is not just cosmetic: it creates contradictory durable truth.

## Phase-1 gate assessment
What passes:
- validated plan persisted on disk
- `status/watch/resume` expose plan state
- execution fails closed if validated durable plan is missing/corrupt before execution
- task fields required by Phase 1 are populated in `plan.json`

What does not fully pass:
- durable truth around plan validity is inconsistent for ambiguity escalations

## Recommendation
Do **not** advance to Phase 2 yet.

Required fix:
- move durable validated-plan creation to occur only after ambiguity escalation checks pass, or
- persist a non-validated planning artifact first and only flip/write `status: validated` after ambiguity + validation gates are both satisfied, and
- add a test proving ambiguous runs do not leave behind a validated `plan.json`.
