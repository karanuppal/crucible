# Phase 5 build notes

Implemented against `docs/crucible-spec-v7.3.2.md` only.

## Phase 5 deliverables completed
- Added a stable runtime embedding API for the OpenClaw front door by exporting named helpers from `crucible.runtime`:
  - `openclaw_run`
  - `openclaw_status`
  - `openclaw_watch`
  - `openclaw_resume`
  - `openclaw_lint`
  - `openclaw_execute`
  - `TOOL_SCHEMA`
- Added explicit OpenClaw entry documentation in `docs/openclaw-entry.md` covering:
  - input contract
  - durable run semantics
  - normalized adapter boundary
  - intended usage of run/status/watch/resume
- Kept OpenClaw-first UX on the same durable substrate by testing named helper calls across `run/status/watch/resume` against one run.
- Kept the normalized OpenClaw adapter boundary honest by updating the adapter/bridge test fixtures to create valid durable plans before exercising the adapter state machine.

## Tests added
- `tests/runtime/test_phase5_openclaw_frontdoor.py`
  - stable runtime embedding API is exported from `crucible.runtime`
  - the same run maps to the same durable semantics across `run/status/watch/resume`
  - a run remains consistently inspectable even when a different OpenClaw surface performs the later inspection

## Notes / boundaries kept
- No Phase 6 hardening, benchmarking, or broader docs cleanup was started.
- This phase stayed focused on OpenClaw front-door productization only.
