# Phase 2 build notes

Implemented against `docs/crucible-spec-v7.3.2.md` only.

## Phase 2 deliverables completed
- Added first-class `ExecutionPacket` model and JSON serializer in `src/crucible/runtime/execution_models.py`.
- Added repo-context extraction with relevant-file selection, preferring explicit `build_target` paths and otherwise doing lightweight description-based matching.
- Wired packet building into the runtime executor for build/repair/debug-style attempts and review attempts.
- Shifted the default solving path away from `verification_command` as the primary worker prompt:
  - `AdapterRunSpec.prompt` now carries task-aware instructions/context.
  - actual shell execution command is passed in `metadata["command"]`.
  - `LocalShellAdapter` executes `metadata["command"]` first, falling back to `prompt` for older callers.
- Added `StructuredExecutionResult` and persisted it in attempt metadata for execution/review attempts.

## Tests added
- `tests/runtime/test_execution_packet_phase2.py`
  - repo summary prefers build targets
  - packet includes repo context, policy snapshot, and prior evidence refs
  - runtime default path uses task-aware packet metadata instead of bare command prompt wiring
- `tests/runtime/test_local_shell_adapter.py`
  - metadata command overrides prompt for task-aware execution

## Notes for later phases
- Strategy memory ref is present in the packet contract but still `None`; Phase 3 should back it with a durable rejection ledger artifact.
- `StructuredExecutionResult` is persisted in attempt metadata, but control-plane terminal enums/transition ownership still need fuller Phase 4+ normalization.
- Repo summarization is intentionally lightweight for Phase 2; richer repo-aware indexing or summaries would be future work.
