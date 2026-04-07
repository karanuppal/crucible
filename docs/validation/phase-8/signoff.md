# Phase 8 Sign-Off — Production Runtime Surface (REWORK)

**Phase:** 8 — Production Runtime Surface
**Spec:** `docs/crucible-spec-v5.3.md`
**Branch:** `phase8-production-runtime`
**Date:** 2026-04-06 (rework)
**Verdict:** ⏳ **PENDING REVIEWER**

The previous signoff (also in this directory's git history) was retracted after a GPT-5.4 reviewer found three blockers:
1. `openclaw_tool.py` had a syntax error and could not import
2. The orchestrator fabricated passing evidence (never executed verification commands)
3. The OpenClaw bridge was a stub ("the embedder will handle this")

This rework addresses all three. The validation plan that drove the rework is at [`VALIDATION-PLAN.md`](./VALIDATION-PLAN.md). Each gate (G1–G7) has automated tests; G8 is the new reviewer pass.

---

## Gate status

| Gate | Description | Status |
|---|---|---|
| **G1** | Every runtime module imports cleanly (`test_imports.py`) | ✅ |
| **G2** | Validation actually executes verification commands (`test_validation_truth.py`) | ✅ |
| **G3** | Default backend is `LocalShellAdapter`, not in-memory (`test_local_shell_adapter.py`) | ✅ |
| **G4** | OpenClaw bridge exists with simulator + production shim (`test_openclaw_bridge.py`) | ✅ |
| **G5** | `crucible run --detach` and `crucible resume` actually execute (`test_resume_executes.py`) | ✅ |
| **G6** | Adversarial test pack (`test_adversarial_phase8.py`) | ✅ |
| **G7** | Full suite + manual smoke | ✅ |
| **G8** | Fresh GPT-5.4 reviewer pass | ⏳ pending |

## Test results

- **479 tests passing**, 0 failures
- 52 new Phase 8 tests added in the rework (on top of the 63 already in place)
- Adversarial pack covers: malformed JSON, vague language, no-must-pass, factory exceptions, no backends, spawn exceptions, idempotent terminal events, restart-then-resume, unknown run_id × 3 commands

## Manual smoke test

End-to-end verified with `LocalShellAdapter` (the new default):

```
$ crucible run good.json   # echo PASSED → expected PASSED
terminal_status: complete  # exit 0

$ crucible run bad.json    # this-cmd-does-not-exist
terminal_status: failed    # exit 3

$ crucible status <run>
status: failed
attempts: 1
```

The reviewer's killer test (`verification_command: "this-command-does-not-exist-12345"` → `terminal_status: complete`) is now `terminal_status: failed`, exit 3.

## What changed in the rework

- **`local_shell_adapter.py`** (NEW): runs real shell commands, checks exit code AND expected substring, reports honestly
- **`openclaw_bridge.py`** (NEW): `SimulatedOpenClawBridge` (for tests) + `SessionsSpawnBridge` (production shim — embedder supplies spawn + wait callables, Crucible owns the rest)
- **`run_executor.py`** (REWRITTEN): executes each criterion's verification triple via the adapter, aggregates honestly. Does NOT delegate evidence collection to the orchestrator anymore.
- **`cli.py`**: default adapter is now `LocalShellAdapter`. `--detach` actually spawns a background process. `resume` actually re-executes.
- **`openclaw_tool.py`**: syntax error fixed, covered by import test
- **`test_imports.py`** (NEW): G1 — every module under `crucible/runtime/` must import or CI fails
- **`test_validation_truth.py`** (NEW): G2 — proves the harness can't be tricked by lying verification commands
- **`test_local_shell_adapter.py`** (NEW): G3
- **`test_openclaw_bridge.py`** (NEW): G4
- **`test_resume_executes.py`** (NEW): G5
- **`test_adversarial_phase8.py`** (NEW): G6

## Architectural decision: split build from verify

The harness no longer pretends a single backend can both build artifacts AND prove they work. The new model:

- **Build phase** (out of band): a real coding agent (Codex, Claude Code, OpenClaw sub-agent) produces artifacts. Embedders wire this via the OpenClaw bridge OR run it themselves.
- **Verify phase** (Crucible's responsibility): for each criterion, run the `verification_command` against the produced artifacts via `LocalShellAdapter` (or a remote-shell variant). Honest pass/fail.

This separation is what makes signoff trustworthy. A build can use whatever model/tool is best; verification is always rooted in real command execution.

## Known limitations

- The default `LocalShellAdapter` does not itself produce artifacts. To use Crucible end-to-end with a real build agent, embedders must drive the build via the OpenClaw bridge before/alongside the verification step. The skill (`skills/openclaw/SKILL.md`) needs to be updated to reflect this — TODO before final signoff.
- Multi-host distributed run store still deferred to Phase 9+.

## Next step

Spawn fresh GPT-5.4 reviewer to validate G8. If the reviewer finds anything critical, fix and re-spawn until clean.
