# Verdict: NOT READY

Round-3’s blocker is **actually fixed**.

But Round 4 uncovered a **new production blocker** and one serious upgrade-compat gap:

1. **Concurrent `resume` is unsafe** — two processes resuming the same run can race on shared run-store files and one can crash with a raw internal error (`exit 5`) while both think they own the run.
2. **Older manifests without `workspace_root` do not resume faithfully** — they do not crash, but they silently fall back to ambient cwd/env and can re-verify in the wrong directory.

That means the durability story is still not production-grade for OpenClaw. The original workspace bug is gone, but the runtime is still missing single-writer discipline and backward-compatible resume recovery.

---

## Repo / test pack state

Observed on commit:

```bash
$ git rev-parse --short HEAD
be2dffc
```

Full suite claim is real:

```bash
$ uv run pytest -q
........................................................................ [ 14%]
........................................................................ [ 28%]
........................................................................ [ 42%]
........................................................................ [ 56%]
........................................................................ [ 70%]
........................................................................ [ 84%]
........................................................................ [ 99%]
.....                                                                    [100%]
509 passed in 8.33s
```

Targeted round-3 regression test also passes:

```bash
$ uv run pytest tests/runtime/test_resume_incremental.py::TestResumeIncremental::test_resume_preserves_workspace_root -q
.                                                                        [100%]
1 passed in 0.08s
```

---

## Round-3 blocker re-verification

## 1) Automated regression is real

The new test exists and is meaningful:
- `tests/runtime/test_resume_incremental.py::test_resume_preserves_workspace_root`
- it starts a run with explicit workspace
- clears `result.json` + attempts
- resumes from another cwd
- asserts success

Relevant fixed code:
- `RunManifest.workspace_root` added: `src/crucible/runtime/run_store.py:37-59`
- persisted in `create_run_store()`: `src/crucible/runtime/run_store.py:441-477`
- `cmd_run()` resolves and persists absolute workspace: `src/crucible/runtime/cli.py:116-136`
- `cmd_resume()` restores `manifest.workspace_root`: `src/crucible/runtime/cli.py:326-338`

## 2) Manual CLI repro of interrupted-run resume

I re-ran the blocker manually using the exact flow the round-3 review asked for:

- start run with explicit `--workspace-root`
- verify manifest persisted it
- delete `result.json` + `attempts/*`
- create the missing artifact in the original workspace
- change cwd
- resume

Observed output:

```text
FIRST RUN RC: 3
FIRST RUN STDOUT:
run_id: run-0b57e8959927
run_root: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-manual-fglteod6/runs/run-0b57e8959927
terminal_status: failed
completed: []
failed: ['t1']
FIRST RUN STDERR:
MANIFEST JSON:
{
  "run_id": "run-0b57e8959927",
  "project_id": "r4-manual",
  "build_id": "b1",
  "run_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-manual-fglteod6/runs/run-0b57e8959927",
  "created_at": 1775535435.885063,
  "spec_text_hash": "ec032adf1d53bd1a",
  "task_definitions_hash": "e932480be9579e20",
  "current_phase": "done",
  "current_status": "failed",
  "cli_version": "0.1.0",
  "embedding_surface": "",
  "embedding_session_ref": "",
  "ledger_ref": "",
  "workspace_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-manual-fglteod6/workspace_a"
}
RESUME RC: 0
RESUME STDOUT:
resumed run run-0b57e8959927
reconciled 0 in-flight attempts
terminal_status: complete
RESUME STDERR:
FINAL RESULT JSON:
{
  "run_id": "run-0b57e8959927",
  "terminal_status": "complete",
  "completed_tasks": [
    "t1"
  ],
  "failed_tasks": [],
  "partial_tasks": [],
  "blocked_reason": "",
  "integration_status": null,
  "total_runtime_seconds": 0.004007816314697266,
  "cost_summary": {
    "backends_used": [
      "local-shell"
    ],
    "total_wall_clock_seconds": 0.004007816314697266,
    "retries_total": 0,
    "subagents_spawned": 1,
    "estimated_tokens": null,
    "notes": ""
  }
}
```

Verdict: **the round-3 blocker is fixed**.

---

## Edge-case review

## A) Relative `--workspace-root`

This now behaves correctly.

`cmd_run()` resolves the workspace up front with `os.path.abspath(...)` before persisting it (`src/crucible/runtime/cli.py:116-122`). I verified it manually with `--workspace-root relws` from cwd `base/`.

Observed output:

```text
RUN RC: 0
RUN STDOUT:
run_id: run-6e01b0be375f
run_root: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-relative-8p_uw0cs/runs/run-6e01b0be375f
terminal_status: complete
completed: ['t1']
failed: []
RUN STDERR:
PERSISTED WORKSPACE_ROOT: /private/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-relative-8p_uw0cs/relws
RESUME RC: 0
RESUME STDOUT:
resumed run run-6e01b0be375f
reconciled 0 in-flight attempts
terminal_status: complete
RESUME STDERR:
```

Verdict: **fixed / acceptable**.

## B) `workspace_root` deleted before resume

This does **not** crash the process. It fails honestly.

Observed output:

```text
RUN RC: 0
RUN STDOUT:
run_id: run-4301af0e683d
run_root: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-missingws-ff7dcrs7/runs/run-4301af0e683d
terminal_status: complete
completed: ['t1']
failed: []
RESUME RC: 3
RESUME STDOUT:
resumed run run-4301af0e683d
reconciled 0 in-flight attempts
terminal_status: failed
...
FINAL RESULT:
{
  "run_id": "run-4301af0e683d",
  "terminal_status": "failed",
  "completed_tasks": [],
  "failed_tasks": [
    "t1"
  ],
  "partial_tasks": [],
  "blocked_reason": "criterion c1 failed: command exited 127: [Errno 2] No such file or directory: '/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-missingws-ff7dcrs7/workspace_a'",
  ...
}
```

This comes from `LocalShellAdapter.spawn()` / `subprocess.run(..., cwd=...)` surfacing the missing cwd as a failure. Not pretty, but materially honest.

Verdict: **not a blocker**. Better UX would be nice, but the behavior is truthful.

## C) Manifest created by older Crucible without `workspace_root`

This does **not** throw a schema error because `RunManifest.workspace_root` has a default (`src/crucible/runtime/run_store.py:52`) and `from_dict()` simply calls `cls(**data)` (`src/crucible/runtime/run_store.py:57-59`).

But correctness is still broken for those runs.

I simulated an old manifest by deleting `workspace_root` from `run.json`, then resumed from a different cwd.

Observed output:

```text
RUN RC: 0
RUN STDOUT:
run_id: run-882247db6e36
run_root: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-oldmanifest-o9gto9zc/runs/run-882247db6e36
terminal_status: complete
completed: ['t1']
failed: []
RESUME RC: 3
RESUME STDOUT:
resumed run run-882247db6e36
reconciled 0 in-flight attempts
terminal_status: failed
RESUME STDERR:
FINAL RESULT:
{
  "run_id": "run-882247db6e36",
  "terminal_status": "failed",
  "completed_tasks": [],
  "failed_tasks": [
    "t1"
  ],
  "partial_tasks": [],
  "blocked_reason": "criterion c1 failed: command exited 1: ",
  ...
}
```

Root cause:
- `cmd_resume()` now uses `manifest.workspace_root or CRUCIBLE_WORKSPACE_ROOT or os.getcwd()` (`src/crucible/runtime/cli.py:326-330`)
- for an old manifest, that field is empty
- so resumed verification again depends on ambient cwd/env

That means pre-fix runs are **not** safely resumable across cwd changes after upgrade.

Verdict: **serious backward-compat gap**.

I would treat this as a blocker for any rolling-upgrade / in-flight-run story. The good news is the event log already records `orchestrator_started` with `workspace_root`, so a migration shim could recover it from historical events.

## D) Multiple processes resuming the same run concurrently

This is the new hard blocker.

There is **no run lock** in `cmd_resume()`.

Both processes can pass:
- `store.is_terminal()` (`src/crucible/runtime/cli.py:300`)
- `store.reconcile_in_flight_attempts()` (`src/crucible/runtime/cli.py:312`)
- `execute_run()` startup (`src/crucible/runtime/cli.py:333-338`)

And the run store uses a **shared fixed temp filename** for atomic JSON writes:

```python
188 def _atomic_write_json(path: str, data: Any) -> None:
189     tmp = path + ".tmp"
190     os.makedirs(os.path.dirname(path), exist_ok=True)
191     with open(tmp, "w") as f:
192         json.dump(data, f, indent=2)
193     os.replace(tmp, path)
```

That is safe for one writer, not for concurrent writers targeting the same `path`.

Manual concurrent-resume repro:
- create a resumable run
- delete `result.json` + `attempts/*`
- start **two** `crucible resume <run_id>` processes at once

Observed output:

```text
INITIAL RUN RC: 0
INITIAL RUN STDOUT:
run_id: run-97d4dc35ba5f
run_root: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-concurrent-35pywads/runs/run-97d4dc35ba5f
terminal_status: complete
completed: ['t1']
failed: []
RESUME1 RC: 0
RESUME1 STDOUT:
resumed run run-97d4dc35ba5f
reconciled 0 in-flight attempts
terminal_status: complete
RESUME1 STDERR:
RESUME2 RC: 5
RESUME2 STDOUT:
RESUME2 STDERR:
internal error: [Errno 2] No such file or directory: '/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-concurrent-35pywads/runs/run-97d4dc35ba5f/run.json.tmp' -> '/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-concurrent-35pywads/runs/run-97d4dc35ba5f/run.json'
Traceback (most recent call last):
  File "/Users/millieclaw/Projects/crucible/src/crucible/runtime/cli.py", line 403, in main
    return args.func(args)
  File "/Users/millieclaw/Projects/crucible/src/crucible/runtime/cli.py", line 333, in cmd_resume
    summary = execute_run(
  File "/Users/millieclaw/Projects/crucible/src/crucible/runtime/run_executor.py", line 69, in execute_run
    store.update_manifest_status("execute", "running")
  File "/Users/millieclaw/Projects/crucible/src/crucible/runtime/run_store.py", line 265, in update_manifest_status
    self.write_manifest(m)
  File "/Users/millieclaw/Projects/crucible/src/crucible/runtime/run_store.py", line 251, in write_manifest
    _atomic_write_json(self.manifest_path, manifest.to_dict())
  File "/Users/millieclaw/Projects/crucible/src/crucible/runtime/run_store.py", line 193, in _atomic_write_json
    os.replace(tmp, path)
FileNotFoundError: [Errno 2] No such file or directory: '/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-concurrent-35pywads/runs/run-97d4dc35ba5f/run.json.tmp' -> '/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-concurrent-35pywads/runs/run-97d4dc35ba5f/run.json'
```

This is not a cosmetic race:
- raw internal error
- no single-writer discipline
- no clean “already resuming” response
- duplicated execution is still possible depending on timing and command side effects

Verdict: **BLOCKER**.

---

## Other stateful gaps resume still has

Beyond `workspace_root`, there is at least one more important ambient dependency:

### Execution backend is not persisted in the durable run record

`cmd_run()` and `cmd_resume()` both hardcode `LocalShellAdapter`:
- `src/crucible/runtime/cli.py:175-180`
- `src/crucible/runtime/cli.py:321-324`

So the durable CLI lifecycle only faithfully resumes **CLI-created local-shell runs**.

If an embedder starts a run through the library with a different adapter factory (for example a `BridgeBackedAdapter` over `SessionsSpawnBridge`), the generic CLI `resume` surface does not know how to restore that execution backend.

That is not the blocker I’m hanging the verdict on today because the shipped `openclaw_tool.execute()` path also shells out to the CLI and therefore uses local shell consistently. But architecturally it means the “durable resume” contract is still narrower than the spec language suggests.

---

## End-to-end walkthrough: what happens for an OpenClaw user now?

## What works

The OpenClaw-facing tool surface is real now.

`crucible.runtime.openclaw_tool.execute()`:
- forces structured CLI output (`src/crucible/runtime/openclaw_tool.py:26-28`)
- passes through `workspace_root`, `embedding_surface`, `embedding_session_ref` via env/args (`src/crucible/runtime/openclaw_tool.py:53-60`, `149-169`)
- returns machine-readable `run_id`, `run_root`, and terminal summary on success

Observed successful tool output:

```json
{
  "exit_code": 0,
  "status": "ok",
  "run_id": "run-50cb43e669b2",
  "run_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r4-tool-po2khvwx/runs/run-50cb43e669b2",
  "terminal_status": "complete",
  "completed_tasks": [
    "t1"
  ],
  "failed_tasks": [],
  "partial_tasks": [],
  "blocked_reason": "",
  "total_runtime_seconds": 0.0040400028228759766
}
```

`status`, `watch`, and `resume` all operate off persisted run-store state instead of live process memory. That is good and real.

## What actually happens on the default path

For the shipped tool/CLI path:

1. OpenClaw calls `openclaw_tool.execute()`.
2. The tool shells out to `python -m crucible.runtime.cli`.
3. `cmd_run()` lints the plan, resolves `workspace_root` to an absolute path, creates `run.json`, `tasks.json`, `events.jsonl`, etc.
4. The foreground CLI path instantiates **`LocalShellAdapter`**, not the OpenClaw bridge (`src/crucible/runtime/cli.py:172-180`).
5. `execute_run()` executes each `verification_command` in that workspace and writes attempts + final result.
6. `resume` now reuses the persisted workspace correctly.

So the default shipped path is a **durable local verifier**.

## Where it still breaks / still falls short

### 1. No single-writer resume discipline

If OpenClaw ends up with two overlapping resumptions for the same run — duplicate user action, retry storm, supervisor bug, operator mistake — one can crash with `exit 5`. That is not production-grade durability.

### 2. Older runs remain ambiguous after upgrade

Runs created before `workspace_root` was persisted are still not recoverable in a cwd-independent way. That is exactly the kind of upgrade edge that bites long-running chat systems.

### 3. The default OpenClaw tool path still does **verification**, not a real sub-agent build loop

The skill itself says this explicitly:
- `LocalShellAdapter` “ONLY runs verification commands locally. It does NOT build anything.” (`skills/openclaw/SKILL.md:14`)
- wiring a real build path is left to an embedder via `SessionsSpawnBridge` (`skills/openclaw/SKILL.md:16`)

So an OpenClaw user saying “build me X” does **not** get a built-in end-to-end sub-agent build pipeline from the shipped tool surface alone. They get a durable verification harness around whatever artifacts already exist or whatever external glue produces them.

That may be an acceptable architecture choice, but it is narrower than the skill’s top-line pitch (“run validated, multi-step software builds via sub-agents”).

---

## Final recommendation

**NOT READY**.

The repo is materially better than Round 3:
- workspace persistence bug is fixed
- relative workspace paths are handled correctly
- missing workspaces fail honestly instead of corrupting state
- 509 tests really do pass

But I would still block production rollout for OpenClaw until the following are fixed:

### Required before signoff

1. **Add per-run single-writer locking around `resume` / terminal-state mutation**
   - lock file or advisory file lock at run-root scope
   - second concurrent resumer must get a clean, deterministic response (`already running`, wait, or no-op)
   - no raw tracebacks

2. **Fix concurrent file writes in the run store**
   - `path + ".tmp"` is not safe for multiple writers to the same file
   - use unique temp names (`.<pid>.<uuid>.tmp`) and/or a lock

3. **Add backward-compat recovery for old manifests without `workspace_root`**
   - recover from `orchestrator_started.payload.workspace_root` in `events.jsonl`
   - or fail explicitly with a clear migration error
   - do not silently fall back to ambient cwd for an existing durable run unless the operator asked for it

4. **Add regression tests for the above**
   - concurrent `resume` same run
   - old manifest missing `workspace_root`
   - missing `workspace_root` recovery from events or explicit refusal

### Strongly recommended next

5. **Persist execution-backend identity / resume contract**
   - if Phase 8 really wants durable OpenClaw-backed runs, resume cannot rely on a hardcoded `LocalShellAdapter` forever

6. **Tighten the skill/docs language**
   - be explicit that the shipped tool surface is a verifier unless extra bridge glue is wired in

If you fix the concurrency/locking issue and the old-manifest recovery story, I would re-run this and expect it to move to **READY WITH CONDITIONS** or possibly **READY** depending on how clean the bridge/resume contract is after that.
