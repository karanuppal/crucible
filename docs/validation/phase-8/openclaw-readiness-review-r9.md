# Verdict: READY WITH CONDITIONS

Commit reviewed: `de337d7`

After re-verifying the Round-8 fix on the actual `openclaw_tool` wrapper path, re-running the targeted tests, re-running the full suite, and reprobing the remaining edge cases, my assessment is:

- the Round-8 blocker is genuinely fixed
- the OpenClaw-facing `resume` contract now works on the healthy path
- the end-to-end OpenClaw user flow (`run` → `status` / `watch` → `resume`) is now coherent
- the remaining issues are real, but they are **conditions / hardening items**, not blocker-class defects for OpenClaw production integration

So this has finally crossed the line from **NOT READY** to **READY WITH CONDITIONS**.

---

## 1) What I re-ran

### Targeted OpenClaw wrapper tests

```bash
uv run pytest tests/runtime/test_openclaw_tool.py -q
```

Result:

```text
19 passed in 0.58s
```

### Prior path-invariant pack (regression check)

```bash
uv run pytest tests/runtime/test_path_invariants.py -q
```

Result:

```text
7 passed in 0.12s
```

### Full suite

```bash
uv run pytest -q
```

Result:

```text
539 passed in 10.16s
```

That matches the claimed suite state.

---

## 2) Round-8 fix re-verification

## A. `openclaw_tool resume` now returns `run_root`

I directly exercised the wrapper, not just the CLI.

Probe pattern:

```python
from crucible.runtime.openclaw_tool import execute

run_out = execute({"mode": "run", ...})
resume_out = execute({"mode": "resume", "run_id": run_out["run_id"], ...})
```

Observed:

```json
{
  "run_out": {
    "exit_code": 0,
    "status": "ok",
    "run_id": "run-1e4038cc5731",
    "run_root": "/.../runs/run-1e4038cc5731",
    "terminal_status": "complete"
  },
  "resume_out": {
    "exit_code": 0,
    "status": "ok",
    "run_id": "run-1e4038cc5731",
    "run_root": "/.../runs/run-1e4038cc5731",
    "workspace_root": "/private/.../workspace",
    "embedding_session_ref": "",
    "terminal_status": "complete"
  }
}
```

Verdict: **fixed**.

`run_root` is present and matches the original run's `run_root`.

---

## B. `workspace_root` is now present on resume

Same wrapper probe above showed:

```json
{
  "workspace_root": "/private/.../workspace"
}
```

This came back from the manifest after resume, which is the right source of truth.

Verdict: **fixed**.

---

## C. `embedding_session_ref` is now present on resume

I tested both the empty and populated cases.

### Case 1: run created without embedding session ref

Observed on resume:

```json
{
  "embedding_session_ref": ""
}
```

This is exactly what the prompt asked for: present, empty string for runs created without one.

### Case 2: run created via wrapper with an embedding session ref

I ran:

```python
execute({
  "mode": "run",
  "embedding_surface": "openclaw",
  "embedding_session_ref": "sess-123",
  ...
})
```

Observed on resume:

```json
{
  "resume_run_root_matches": true,
  "resume_workspace_root": "/private/.../workspace",
  "resume_embedding_session_ref": "sess-123",
  "resume_status": "ok",
  "resume_terminal_status": "complete"
}
```

Verdict: **fixed**.

---

## D. Full round-trip via the wrapper works

I walked the actual wrapper flow an OpenClaw caller would use:

1. `execute({mode: "run", ...})`
2. `execute({mode: "status", run_id: ...})`
3. `execute({mode: "watch", run_id: ...})`
4. `execute({mode: "resume", run_id: ...})`

Observed summary:

```json
{
  "run": {
    "status": "ok",
    "exit_code": 0,
    "run_id": "run-03ccd2cd18bb",
    "run_root": "/.../runs/run-03ccd2cd18bb",
    "terminal_status": "complete"
  },
  "status": {
    "status": "ok",
    "exit_code": 0,
    "run_id": "run-03ccd2cd18bb",
    "phase": "done",
    "is_terminal": true,
    "terminal_status": "complete"
  },
  "watch_event_count": 8,
  "watch_first_event_type": "run_started",
  "resume": {
    "status": "ok",
    "exit_code": 0,
    "run_id": "run-03ccd2cd18bb",
    "run_root": "/.../runs/run-03ccd2cd18bb",
    "workspace_root": "/private/.../workspace",
    "embedding_session_ref": "topic-6442",
    "terminal_status": "complete"
  }
}
```

Verdict: **works end-to-end on the OpenClaw wrapper path**.

---

## 3) Re-assessment of remaining conditions

## A. Relative `CRUCIBLE_RUNS_DIR` is still cwd-anchored

I reprobed this explicitly.

Flow:

```bash
cd /tmp/a
PYTHONPATH=... python3 -m crucible.runtime.cli --runs-dir runs run ...
cd /tmp/b
PYTHONPATH=... python3 -m crucible.runtime.cli status <run_id> --json
```

Observed:

```json
{
  "run_id": "run-b2fda9cf8ed9",
  "status_without_runs_dir_exit": 4,
  "status_without_runs_dir_output": "unknown run_id: run-b2fda9cf8ed9",
  "status_with_absolute_runs_dir_exit": 0,
  "status_with_absolute_runs_dir_manifest_run_root": "/private/.../a/runs/run-b2fda9cf8ed9"
}
```

### Is this a blocker?

For generic CLI ergonomics: annoying, yes.

For **OpenClaw production integration**: **not a blocker**.

Why:

- OpenClaw callers can and should persist `runs_dir`
- the wrapper now returns `run_root`, so a caller can also derive `runs_dir = dirname(run_root)` if needed
- production integrations should use an **absolute** runs dir anyway
- this is a discoverability / path-policy issue, not a correctness failure on the supported wrapper path

This should stay documented as a condition:

- bare `run_id` is not globally discoverable across cwd changes
- relative runs roots are invocation-cwd semantics, not portable identifiers

---

## B. `run_root` is absolute but not `realpath()`-canonical when runs dir is a symlink

I reprobed with a symlinked runs directory.

Observed:

```json
{
  "event_run_root": "/var/.../link-runs/run-f3d0992a7136",
  "manifest_run_root": "/var/.../link-runs/run-f3d0992a7136",
  "realpath_manifest_run_root": "/private/var/.../real-runs/run-f3d0992a7136",
  "is_absolute": true,
  "uses_realpath": false
}
```

### Is this a blocker?

**No.**

This is a purity / invariant issue, not a live OpenClaw integration break.

The stored path:

- is absolute
- points to the correct directory
- is stable enough for callers to use

Unlike the old `workspace_root` bug, this does **not** create a manifest/execution mismatch on the main path.

If the project wants the stronger invariant "all persisted paths are canonical realpaths," then `run_root` still does not satisfy that. But I do not think that is strong enough to block production integration.

---

## C. Lower-layer cwd fallbacks still exist

I confirmed the reviewer's note by grep:

- `src/crucible/runtime/run_store.py:192` → `CRUCIBLE_RUNS_DIR` default anchored to `os.getcwd()`
- `src/crucible/runtime/run_executor.py:67` → `workspace_root = os.path.abspath(workspace_root or os.getcwd())`
- `src/crucible/runtime/local_shell_adapter.py:107` → `cwd = spec.cwd or os.getcwd()`
- `src/crucible/orchestrator/orchestrator.py:219` → legacy path still uses `cwd=os.getcwd()`

### Is this a blocker?

For the **current OpenClaw / CLI path**: **no**.

Why:

- `cmd_run()` canonicalizes and passes `workspace_root`
- `cmd_resume()` restores/pins `workspace_root` and refuses ambient-cwd fallback on old runs without an explicit override
- the OpenClaw wrapper is calling those guarded paths, not the raw lower layers directly

So the dangerous path drift that mattered for production integration has been closed on the actual entrypoints.

This remains a condition for future embedders:

- if someone bypasses the CLI / wrapper and calls lower layers sloppily, they can still reintroduce cwd-coupled behavior
- that is a library-hardening concern, not a current OpenClaw readiness blocker

---

## 4) One last thing I checked: is the Round-8 fix only "best effort"?

Yes: `_do_resume()` swallows introspection failures after the CLI call.

I do **not** consider that blocker-class.

Reason:

- on healthy runs, the contract now works and I verified it directly
- for a successful CLI resume to be followed by a failed local manifest lookup, something more fundamental has already gone wrong (run store disappeared, became unreadable, or was corrupted between the two steps)
- in that situation, returning a partial structured error is acceptable; the system already has a broader filesystem integrity problem

That said, the test coverage is still narrower than the implemented contract:

- current automated test asserts `run_root`
- it does **not** yet assert `workspace_root`
- it does **not** yet assert `embedding_session_ref`

I would add those assertions. I do **not** require them before production use.

---

## 5) End-to-end OpenClaw walkthrough: is the user story finally sound?

## What the OpenClaw caller can now rely on

### Start a run

`execute({mode: "run", ...})` returns:

- `status`
- `exit_code`
- `run_id`
- `run_root`
- terminal summary fields when the run finishes inline

### Inspect progress

`status` and `watch` work as structured machine interfaces.

### Resume a run

`execute({mode: "resume", run_id, runs_dir})` now returns:

- `run_id`
- `run_root`
- `workspace_root`
- `embedding_session_ref`
- terminal summary when available

That was the missing machine-contract piece in Round 8. It is now there.

## What the caller still needs to do correctly

The caller must:

- persist the run locator (`runs_dir`, or derive it from `run_root`)
- prefer absolute runs dirs in production
- avoid assuming a relative runs root is magically discoverable from any later cwd

Those are reasonable integration conditions, not hidden correctness traps.

## Bottom line on the user journey

A real OpenClaw user invoking Crucible now has a coherent flow:

- create run
- get durable run identifiers back
- inspect the run later
- resume it later
- recover the pinned workspace/session metadata on resume

That is the production bar that was still missing last round.

---

## 6) Final recommendation

## Release recommendation

**READY WITH CONDITIONS**

I would allow production OpenClaw integration with the following explicit operating guidance:

1. **Use absolute `runs_dir` in production** whenever possible.
2. **Persist `runs_dir` or derive it from `run_root`** instead of assuming `run_id` is globally discoverable.
3. **Treat lower-layer runtime modules as internal APIs** unless you also pass explicit path context.
4. **Add follow-up test coverage** for resume returning `workspace_root` and `embedding_session_ref`.

## Why this is no longer `NOT READY`

Because the last actual blocker was the wrapper contract break on `resume`, and that is now fixed on the real execution path.

## Why this is not plain `READY`

Because the remaining path semantics should be called out honestly:

- relative runs-dir lookup is still cwd-relative
- `run_root` is not yet symlink-canonical
- lower-level fallbacks still exist for careless embedders

Those are real conditions. They are just not severe enough to keep OpenClaw integration out of production.

If you want the brutal one-line version:

**Yes — for OpenClaw integration, this is finally production-ready enough to ship, provided the caller uses explicit run-location discipline.**
