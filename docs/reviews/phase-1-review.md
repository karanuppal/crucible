# Phase 1 review against `docs/crucible-spec-v7.3.2.md`

## Verdict
NEEDS FIXES

## Scope reviewed
- `docs/crucible-spec-v7.3.2.md` (Phase 1 + release gates)
- `docs/implementation/phase-1-build-notes.md`
- `src/crucible/planning/__init__.py`
- `src/crucible/planning/plan.py`
- `src/crucible/runtime/run_store.py`
- `src/crucible/runtime/cli.py`
- `src/crucible/runtime/openclaw_tool.py`
- `tests/runtime/test_cli.py`
- `tests/runtime/test_openclaw_tool.py`
- HEAD commit `ae5ad6d` stats and touched files

## What is correctly implemented
- A real `planning/` subsystem now exists with:
  - `detect_ambiguity()`
  - `build_plan_artifact()`
  - `validate_plan_artifact()`
  - `ensure_validated_plan()`
- Durable `plan.json` persistence exists in `RunStore`:
  - `plan_path`, `write_plan()`, `read_plan()`
  - manifest fields `plan_ref` and `plan_status`
- CLI `run` path:
  - lints the submitted plan
  - runs ambiguity detection
  - builds/writes validated durable plan
  - appends `plan_validated` event
  - refuses execution if `ensure_validated_plan(store.read_plan())` fails
- CLI `resume` path hard-fails when durable plan is missing/invalid for non-terminal runs.
- OpenClaw tool path mirrors the same gate for both normal CLI-backed mode and bridge-backed direct mode.
- `status` surfaces the plan artifact itself (`plan`, `plan_present`, `plan_status`, `plan_path`).
- `resume` surfaces plan state/path in both CLI and OpenClaw wrapper.
- Tests do cover the main happy-path artifacts and missing-plan rejection on resume.

## What is missing / weak vs Phase 1 requirements

### 1) The gate is not a runtime-core invariant
The spec says “no real execution begins without validated `plan.json`.” In shipped code, that is true for the reviewed CLI/OpenClaw entry paths, but not as a hard library/runtime invariant:
- `execute_run()` itself is not gated.
- `create_run_store()` silently tries to auto-create a validated plan from the normalized task snapshot and then **swallows all exceptions**.

That means low-level callers can still create runs whose plan state is effectively “best effort,” not enforced truth. For a library-first substrate, this is too soft.

### 2) `create_run_store()` muddies the meaning of the plan gate
Build notes call Phase 1 a “plan gate,” but `create_run_store()` eagerly synthesizes `plan.json` from `task_plan`. That is convenient, but architecturally it weakens the claim that planning is a distinct, explicit gate. It acts more like opportunistic normalization than a strict planning boundary.

### 3) Watch does not really expose current plan state
Phase 1 tests/spec say `status/watch/resume` expose plan state. In practice:
- `status`: yes
- `resume`: yes
- `watch`: only indirectly via historical `plan_validated` event, not a stable current snapshot field or plan artifact pointer outside replaying events

That is weaker than the spec wording.

### 4) Ambiguity detector exists, but it is extremely shallow
It only scans for empty spec / marker tokens (`tbd`, `todo`, `???`, etc.). That satisfies “an ambiguity detector exists,” but not a strong release-quality planning gate. At minimum, it is heuristic and easily bypassed.

### 5) Docs mismatch the claimed source of truth
`docs/crucible-spec-v7.3.2.md` is the file under review, but its title says **v7.3.1**. Phase gates require docs to match shipped behavior. This is a real release-gate blemish, especially when the build notes explicitly cite 7.3.2.

### 6) Test proof is narrower than the release-gate claim
Good tests were added, but they prove mainly:
- validated plan persists
- `status` shows plan
- `watch` replays a `plan_validated` event
- `resume` rejects missing durable plan

They do **not** prove a harder invariant like “all execution entrypoints fail closed if plan validation is skipped or corrupted before execution.”

## Should Phase 2 start?
Not yet. This is close, but I would not call Phase 1 “complete and shippable” under the 7.3.2 release-gate wording until the gate becomes stricter and the docs/output semantics are cleaner.

## Top fixes required
1. Make validated-plan enforcement a runtime invariant, not just CLI/OpenClaw wrapper behavior.
2. Remove the silent `except Exception: pass` around auto-plan creation in `create_run_store()` or replace it with explicit failure/recorded invalid plan state.
3. Decide whether `watch` should expose current plan state directly; if yes, add it and test it.
4. Fix the version/document mismatch in `docs/crucible-spec-v7.3.2.md`.
5. Add one adversarial test proving execution cannot proceed if `plan.json` is deleted/corrupted before initial execution, not only on resume.
