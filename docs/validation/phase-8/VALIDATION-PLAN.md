# Phase 8 Validation Plan — MUST-PASS BEFORE ANY SIGNOFF

This file is the contract. If a single item below is unchecked, Phase 8 is NOT signed off, regardless of test count or reviewer optimism.

Lesson from the first reviewer round: 427 tests passed but the harness fabricated validation evidence and the tool wrapper had a syntax error. Tests on the happy path are not enough. Every claim must be **adversarially verified**.

---

## Hard Gates (all must be ✅ before signoff)

### G1. Every shipped Python module imports cleanly
- [ ] `python -c "import crucible.runtime.cli"` → exits 0
- [ ] `python -c "import crucible.runtime.run_store"` → exits 0
- [ ] `python -c "import crucible.runtime.preflight"` → exits 0
- [ ] `python -c "import crucible.runtime.openclaw_adapter"` → exits 0
- [ ] `python -c "import crucible.runtime.openclaw_tool"` → exits 0
- [ ] `python -c "import crucible.runtime.run_executor"` → exits 0
- [ ] `python -c "import crucible.runtime.plan_loader"` → exits 0
- [ ] `python -c "import crucible.runtime.openclaw_bridge"` → exits 0
- [ ] **Automated:** `tests/runtime/test_imports.py` enumerates every module under `crucible/runtime/` and asserts each imports without error. CI runs this first.

### G2. Validation must actually validate (anti-fabrication)
A criterion's `verification_command` MUST be executed against the produced artifacts. If the command fails or its output does not match `expected_output`, the criterion MUST be FAIL and the task MUST be FAIL.

- [ ] `tests/runtime/test_validation_truth.py::test_failing_command_fails_task` — plan with `verification_command: "false"` → run completes with `terminal_status: failed`
- [ ] `tests/runtime/test_validation_truth.py::test_wrong_expected_output_fails_task` — command returns "BAR" but `expected_output: "FOO"` → run fails
- [ ] `tests/runtime/test_validation_truth.py::test_nonexistent_command_fails_task` — `verification_command: "this-does-not-exist-12345"` → run fails (this is the exact case the reviewer broke us with)
- [ ] `tests/runtime/test_validation_truth.py::test_passing_command_passes_task` — command returns "PASSED" matching `expected_output: "PASSED"` → run completes
- [ ] `tests/runtime/test_validation_truth.py::test_partial_pass_marks_partial` — 2 tasks, one passes verification, one fails → terminal_status: partial

### G3. The default backend cannot rubber-stamp
The CLI's default adapter MUST run real verification commands locally. The InMemoryAdapter's "I always succeed" path may exist for unit tests but MUST NOT be the CLI default.

- [ ] CLI default adapter is `LocalShellAdapter` (new), not `InMemoryAdapter`
- [ ] `tests/runtime/test_local_shell_adapter.py::test_executes_real_command`
- [ ] `tests/runtime/test_local_shell_adapter.py::test_captures_stdout_and_exit_code`
- [ ] `tests/runtime/test_local_shell_adapter.py::test_failing_command_marked_failed`
- [ ] `tests/runtime/test_local_shell_adapter.py::test_timeout_marks_timed_out`

### G4. OpenClaw bridge exists and is exercised
A reference bridge MUST exist inside Crucible (not "owned by the embedder"). It MUST be importable and have a tested simulator path.

- [ ] `src/crucible/runtime/openclaw_bridge.py` exists with documented public API
- [ ] Has a `SimulatedOpenClawBridge` class for tests
- [ ] Has a `SessionsSpawnBridge` shim that takes a `sessions_spawn` callable + an event-ingestion callback (the contract OpenClaw will wire to)
- [ ] `tests/runtime/test_openclaw_bridge.py` covers: spawn → terminal complete event → adapter state updated; spawn → terminal failed event → adapter state failed; spawn → kill request → killed
- [ ] An e2e test runs `crucible run` with the simulated bridge driving real backend execution and asserts the run completes via the bridge path

### G5. CLI commands all do something real
- [ ] `crucible run` foreground → completes, writes result.json, exits 0/3 correctly
- [ ] `crucible run --detach` → returns immediately, leaves a runnable record. **Test:** subsequent `crucible status` then `crucible resume` actually drives execution to completion.
- [ ] `crucible resume` of a non-terminal run → executes remaining work (not just logs a note). **Test:** `tests/runtime/test_resume_executes.py`
- [ ] `crucible status` returns truthful state for all 5 phases (intake, execute, validate, done, blocked)
- [ ] `crucible watch` streams events as they happen (not just snapshot of past events)
- [ ] `crucible lint-plan` exit codes verified for each failure mode

### G6. Adversarial test pack
At least one test for each known foot-gun:

- [ ] **Bad plan ingestion:** malformed JSON, missing fields, vague language → all rejected with exit 2
- [ ] **Lying verification:** `verification_command` that always exits 0 but produces no real evidence → detected? (At minimum, expected_output mismatch must fail)
- [ ] **Crash mid-run:** simulated orchestrator crash → run dir exists, can be loaded, status reflects partial state, in-flight attempts marked needs_reconciliation
- [ ] **Restart-then-resume:** create run, kill process simulation, resume → run reaches a terminal state
- [ ] **Concurrent ingest_event for same handle:** terminal state idempotency
- [ ] **Unknown run_id:** all subcommands return exit 4
- [ ] **Adapter spawn raises exception:** run terminates cleanly with failed status, not orphaned
- [ ] **Empty plan tasks:** rejected by preflight
- [ ] **Plan with single task that has 0 must_pass criteria:** rejected by preflight

### G7. The CI command
A single command that runs everything and fails loudly on any error:

```
cd ~/Projects/crucible && uv run pytest tests/ -x --tb=short
```

- [ ] All 427+ tests pass
- [ ] No skipped tests in `tests/runtime/`
- [ ] No deprecation warnings in new modules
- [ ] Manual smoke test passes:
  - [ ] `crucible run plan-good.json` → exit 0, terminal complete
  - [ ] `crucible run plan-bad-cmd.json` → exit 3, terminal failed
  - [ ] `crucible status <id>` → matches reality
  - [ ] `crucible watch <id> --from 0` → emits all events

### G8. Reviewer pass
A fresh GPT-5.4 reviewer agent reviews the branch and finds:
- [ ] No syntax errors in any module
- [ ] No "validation theater" — verification commands actually execute
- [ ] No "embedder will handle this" stubs in the user-facing surface
- [ ] No critical risks marked BLOCKER
- [ ] At most LOW/MEDIUM-severity findings remaining

If the reviewer finds anything critical, fix it and re-spawn another reviewer. Loop until clean.

---

## Implementation Order (do not skip steps)

1. Fix syntax error in `openclaw_tool.py` + add `test_imports.py` (G1)
2. Build `LocalShellAdapter` + tests (G3)
3. Wire orchestrator to actually execute verification commands via the validation ladder (G2)
4. Build `openclaw_bridge.py` with simulator + tests (G4)
5. Implement `--detach` and `resume` execution paths (G5)
6. Write the adversarial test pack (G6)
7. Run the full CI command (G7)
8. Spawn reviewer (G8); if critical findings, GOTO 1
9. Only THEN: update signoff.md
