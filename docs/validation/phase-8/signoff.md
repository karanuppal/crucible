# Phase 8 Sign-Off — Production Runtime Surface

**Phase:** 8 — Production Runtime Surface (CLI + Run Store + Preflight + OpenClaw Adapter)
**Spec:** `docs/crucible-spec-v5.3.md`
**Branch:** `phase8-production-runtime`
**Date:** 2026-04-06
**Verdict:** ✅ **READY**

---

## Deliverables

| Item | Path | Status |
|---|---|---|
| Spec v5.3 Phase 8 addendum | `docs/crucible-spec-v5.3.md` | ✅ |
| Productionization review | `docs/validation/phase-8/productionization-review.md` | ✅ |
| Spec consistency check | `docs/validation/phase-8/spec-v5.3-consistency-check.md` | ✅ |
| Validation matrix | `docs/validation/phase-8/validation-matrix.md` | ✅ |
| **Run store** | `src/crucible/runtime/run_store.py` | ✅ |
| **Preflight validator** | `src/crucible/runtime/preflight.py` | ✅ |
| **Plan loader** | `src/crucible/runtime/plan_loader.py` | ✅ |
| **OpenClaw sub-agent adapter** | `src/crucible/runtime/openclaw_adapter.py` | ✅ |
| **Run executor (orchestrator bridge)** | `src/crucible/runtime/run_executor.py` | ✅ |
| **CLI** | `src/crucible/runtime/cli.py` | ✅ |
| **OpenClaw tool wrapper** | `src/crucible/runtime/openclaw_tool.py` | ✅ |
| **Skill + plan templates** | `skills/openclaw/SKILL.md` | ✅ |
| pyproject script entry | `pyproject.toml` `[project.scripts] crucible` | ✅ |
| Phase 8 tests | `tests/runtime/` | ✅ |

## Test Results

- **427 tests passing**, 0 failures
- **63 new tests** added in Phase 8 (run_store, preflight, openclaw_adapter, cli, e2e)
- **0 regressions** in Phase 1–7 test suite (364 tests)

## Manual smoke test

End-to-end verified with default in-memory adapter:
- `crucible run` → completes successfully, writes `result.json`
- `crucible status` → reports `terminal_status: complete`
- `crucible watch` → replays full event stream
- `crucible lint-plan` → exits 2 on bad plans, 0 on good

## Architectural Decisions Locked

1. **Library-first.** CLI is a thin shell over `Orchestrator`. Embedders can call `execute_run()` directly.
2. **One Orchestrator ↔ one RunManifest.** No shared state across runs.
3. **Hybrid planning.** LLM drafts plans; Crucible-side preflight validator gates intake at `crucible run` time.
4. **`needs_reconciliation: bool`** replaces the old "unknown" status — explicit, not implicit.
5. **Adapter state is authoritative on disk.** Process restarts are recoverable by construction; no in-memory listener state required.
6. **Exit codes:** 0=success · 1=usage · 2=lint fail · 3=blocked/failed · 4=unknown run · 5=internal.
7. **Embedding session tracked on RunManifest** for cross-surface continuity (`embedding_surface`, `embedding_session_ref`).

## Known limitations (deferred to Phase 9+)

- Real OpenClaw event bridge wiring is owned by the embedding layer (interface contract complete; the bridge itself is OpenClaw-side).
- Single-host filesystem only — no distributed run store.
- Default CLI uses InMemoryAdapter; production embedders inject real adapters via `execute_run(adapter_factory=...)`.

## Recommendation

**Phase 8 is ready to ship.** Branch `phase8-production-runtime` should be merged into `main` after review. The OpenClaw embedding layer can begin Phase 8.5 (real event-bridge wiring) immediately against the documented `ingest_event()` contract.
