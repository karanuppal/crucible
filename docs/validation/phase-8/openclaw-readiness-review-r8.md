# Verdict: NOT READY

Commit reviewed: `f0b1c0a` (plus `3893eff` cleanup)

Round-7’s two stated fixes are real. I re-ran the new tests, re-ran the full suite, and reprobed the exact edge cases that failed in Round 7:
- env-var first-pin on old runs now canonicalizes correctly
- `manifest.run_root` is now absolute even when `--runs-dir` / `CRUCIBLE_RUNS_DIR` is relative

So the Round-7 blockers are fixed.

But I found one **new blocker-class issue in the OpenClaw-facing machine interface**:

1. **`openclaw_tool` still violates its own `resume` contract by omitting `run_root`.**
   - The wrapper docstring says `run_root` is “always present after run/resume/detach”.
   - `_do_resume()` never populates it.
   - Repro below shows `run` returns `run_root`, `resume` does not.
   - For an OpenClaw caller, that is a real contract break on a core path.

I also found two **important non-blocking conditions**:
- relative `CRUCIBLE_RUNS_DIR` is still **cwd-anchored at invocation time**, so `status/watch/resume` in a different cwd will not rediscover the run unless the caller re-supplies the same runs root
- `run_root` is now absolute, but **not canonicalized through `realpath()`**, so a symlinked runs dir still persists the symlink spelling

Because this review is specifically about **OpenClaw readiness**, and the OpenClaw wrapper still lies about its structured output on `resume`, the verdict remains **NOT READY**.

---

## 1) Test pack state

### Targeted Round-7 tests

Command:

```bash
uv run pytest tests/runtime/test_path_invariants.py -q
```

Output:

```text
.......                                                                  [100%]
7 passed in 0.13s
```

### Full suite

Command:

```bash
uv run pytest -q
```

Output:

```text
538 passed in 10.20s
```

So this is not a red-suite problem. It is a next-layer contract/readiness problem.

---

## 2) Round-7 fix re-verification

## A. Env-var first-pin on old runs is now canonicalized correctly

Relevant code:
- `src/crucible/runtime/cli.py:360-393`
- `src/crucible/runtime/run_executor.py:67-68`

`cmd_resume()` now canonicalizes the old-run override through `_canonicalize_workspace()` before persisting and before calling the executor:

```python
workspace_root = _canonicalize_workspace(raw_override)
manifest.workspace_root = workspace_root
store.write_manifest(manifest)
```

And the executor emits the same path string:

```python
workspace_root = os.path.abspath(workspace_root or os.getcwd())
store.append_event("orchestrator_started", payload={"workspace_root": workspace_root})
```

### Probe: symlinked env var on old run

Command:

```bash
CRUCIBLE_WORKSPACE_ROOT=/tmp/link_ws \
python -m crucible.runtime.cli --runs-dir /tmp/runs1 resume <run_id>
```

Observed result:

```json
{
  "returncode": 0,
  "stdout": "resumed run run-aceffd7ea2cd\nreconciled 0 in-flight attempts\nterminal_status: complete",
  "manifest_workspace_root": "/private/.../real_ws",
  "orchestrator_started_workspace_root": "/private/.../real_ws",
  "matches_realpath": true
}
```

Verdict: **fixed**.

### Probe: relative env var on old run

Command:

```bash
(cd /tmp/case2 && \
  CRUCIBLE_WORKSPACE_ROOT=rel_ws \
  python -m crucible.runtime.cli --runs-dir /tmp/runs2 resume <run_id>)
```

Observed result:

```json
{
  "returncode": 0,
  "stdout": "resumed run run-0ebcaa5177f6\nreconciled 0 in-flight attempts\nterminal_status: complete",
  "manifest_workspace_root": "/private/.../case2/rel_ws",
  "orchestrator_started_workspace_root": "/private/.../case2/rel_ws",
  "expected": "/private/.../case2/rel_ws",
  "matches_expected": true
}
```

Verdict: **fixed**.

### Probe: CLI flag and env var now produce identical results

Observed result:

```json
{
  "cli_returncode": 0,
  "env_returncode": 0,
  "cli_manifest_workspace_root": "/private/.../real_ws",
  "env_manifest_workspace_root": "/private/.../real_ws",
  "cli_event_workspace_root": "/private/.../real_ws",
  "env_event_workspace_root": "/private/.../real_ws",
  "identical_results": true
}
```

Verdict: **fixed**.

---

## B. `manifest.run_root` is now absolute for relative runs dirs

Relevant code:
- `src/crucible/runtime/run_store.py:186-193`
- `src/crucible/runtime/run_store.py:572-577`
- `src/crucible/runtime/run_store.py:601-608`

Key changes verified:

```python
raw = os.environ.get("CRUCIBLE_RUNS_DIR", os.path.join(os.getcwd(), "runs"))
return os.path.abspath(raw)
```

```python
runs_root = os.path.abspath(runs_root)
run_root = os.path.join(runs_root, run_id)
```

### Probe: `--runs-dir relative-runs`

Command:

```bash
(cd /tmp/case4 && \
  python -m crucible.runtime.cli --runs-dir relative-runs \
  run /tmp/case4/plan.json --workspace-root /tmp/case4/ws --jsonl)
```

Observed result:

```json
{
  "returncode": 0,
  "run_started_event_run_root": "/private/.../case4/relative-runs/run-c213b2c87e1e",
  "manifest_run_root": "/private/.../case4/relative-runs/run-c213b2c87e1e",
  "isabs_event": true,
  "isabs_manifest": true
}
```

Verdict: **fixed**.

### Probe: `CRUCIBLE_RUNS_DIR=relative-runs`

Command:

```bash
(cd /tmp/case5 && \
  CRUCIBLE_RUNS_DIR=relative-runs \
  python -m crucible.runtime.cli run /tmp/case5/plan.json \
  --workspace-root /tmp/case5/ws --jsonl)
```

Observed result:

```json
{
  "returncode": 0,
  "run_started_event_run_root": "/private/.../case5/relative-runs/run-3ed11cf17259",
  "manifest_run_root": "/private/.../case5/relative-runs/run-3ed11cf17259",
  "isabs_event": true,
  "isabs_manifest": true
}
```

Verdict: **fixed**.

### Probe: resume of a run created via relative runs dir

Command:

```bash
(cd /tmp/case4 && \
  python -m crucible.runtime.cli --runs-dir relative-runs resume run-c213b2c87e1e)
```

Observed result:

```json
{
  "returncode": 0,
  "stdout": "already terminal: complete",
  "manifest_run_root_after_resume": "/private/.../case4/relative-runs/run-c213b2c87e1e",
  "isabs_manifest_after_resume": true
}
```

Verdict: **fixed**.

---

## 3) New blocker

## [BLOCKER] `openclaw_tool` still breaks its structured `resume` contract

This one is outside the Round-7 path fixes, but it directly affects the end-to-end OpenClaw flow.

### The contract says one thing

`src/crucible/runtime/openclaw_tool.py:15-20`:

```python
Output (dict):
  status: str
  exit_code: int
  run_id: str          # always present after run/resume/detach
  run_root: str        # always present after run/resume/detach
```

### The implementation says another

`src/crucible/runtime/openclaw_tool.py:244-274`:

```python
def _do_resume(...):
    ...
    out: dict[str, Any] = {"exit_code": rc, "status": _exit_to_status(rc), "run_id": run_id}
    ...
    return out
```

There is **no path** in `_do_resume()` that sets `run_root`.

### Reproduction

Command:

```python
from crucible.runtime.openclaw_tool import execute

run_out = execute({"mode": "run", ...})
resume_out = execute({"mode": "resume", "run_id": run_out["run_id"], ...})
```

Observed output:

```json
{
  "run": {
    "exit_code": 0,
    "status": "ok",
    "run_id": "run-6000031ad7a0",
    "run_root": "/var/folders/.../runs/run-6000031ad7a0",
    "terminal_status": "complete"
  },
  "resume": {
    "exit_code": 0,
    "status": "ok",
    "run_id": "run-6000031ad7a0",
    "terminal_status": "complete"
  }
}
```

### Why I consider this blocker-class

This wrapper is supposed to be the **machine interface** for OpenClaw.
If it says `run_root` is always present after `resume`, callers are allowed to depend on that.
Right now they cannot.

That means an OpenClaw caller that resumes a run and then wants to locate:
- `run.json`
- `events.jsonl`
- `artifacts/`
- attempt records

cannot do so from the documented response contract.

A production wrapper cannot lie about its structured output.

### Required fix

At least one of:
- include `run_root` in CLI `resume` structured output (`resumed` / `already_terminal` event)
- or have `_do_resume()` read the manifest after resume and populate `run_root`

And add tests for both:
- resume on already-terminal run returns `run_root`
- resume on non-terminal run returns `run_root`

---

## 4) Important non-blocking conditions / next-layer findings

## A. Relative `CRUCIBLE_RUNS_DIR` is still cwd-sensitive for later lookup

This is the semantic question you explicitly asked about.

### What happens

If the user does:

```bash
cd /a
CRUCIBLE_RUNS_DIR=runs crucible run plan.json
cd /b
crucible status <id>
```

then `status` **does not** find the run unless the same runs root is supplied again.

### Reproduction

Observed result:

```json
{
  "status_without_runs_dir_returncode": 4,
  "status_without_runs_dir_stderr": "unknown run_id: run-7c7582587922",
  "status_with_absolute_runs_dir_returncode": 0,
  "status_with_absolute_runs_dir_manifest_run_root": "/private/.../cwd-a/runs/run-7c7582587922"
}
```

### Why

Because lookup still works by:
- `--runs-dir`
- else `CRUCIBLE_RUNS_DIR`
- else `os.getcwd()/runs`

See `src/crucible/runtime/run_store.py:186-193` and `src/crucible/runtime/cli.py:214-215, 261-262, 308-309`.

### My take

This is **not automatically a blocker** if documented as intended CLI semantics.
But it is absolutely a condition:
- embedders must persist and reuse `runs_dir`
- production callers should prefer an **absolute** runs dir
- a bare `run_id` is **not globally discoverable** across cwd changes

For OpenClaw specifically: if the caller does not carry the same `runs_dir` across `run/status/watch/resume`, it can still drift even though `manifest.run_root` is absolute.

---

## B. `run_root` is absolute, but not canonical for symlinked runs dirs

The Round-7 fix uses `abspath()`, not `realpath()`.

Relevant code:
- `src/crucible/runtime/run_store.py:192-193`
- `src/crucible/runtime/run_store.py:576`
- `src/crucible/runtime/run_store.py:604`

### Reproduction

I created a symlinked runs directory and ran:

```bash
python -m crucible.runtime.cli --runs-dir /tmp/link-runs run ...
```

Observed result:

```json
{
  "run_started_event_run_root": "/var/.../link-runs/run-b4f28896a7bb",
  "manifest_run_root": "/var/.../link-runs/run-b4f28896a7bb",
  "realpath_manifest_run_root": "/private/var/.../real-runs/run-b4f28896a7bb",
  "uses_realpath": false
}
```

### My take

This is **not the same class of blocker** as the old workspace bug.
Why:
- `run_root` is a locator for the run store itself
- symlink spelling still points to the same directory
- there is no current manifest/execution mismatch created by this

But if the desired invariant is “all persisted paths are canonical realpaths,” then that invariant is **still false for run_root**.

So: not a release blocker by itself, but worth deciding explicitly.

---

## C. Remaining cwd fallbacks still exist in lower layers

I grepped the runtime for path fallbacks and found:

- `src/crucible/runtime/run_store.py:192`
  - `CRUCIBLE_RUNS_DIR` default is still anchored to `os.getcwd()`
- `src/crucible/runtime/run_executor.py:67`
  - falls back to `os.getcwd()` if `workspace_root` not passed
- `src/crucible/runtime/local_shell_adapter.py:107`
  - falls back to `spec.cwd or os.getcwd()`
- `src/crucible/orchestrator/orchestrator.py:219`
  - legacy path still hardcodes `cwd=os.getcwd()`

### My take

For the **current CLI path**, this is mostly okay because:
- `cmd_run()` now always resolves and passes `workspace_root`
- `cmd_resume()` now restores/pins and passes `workspace_root`

So I do **not** see an active blocker here on the main path.

But these fallbacks still mean direct embedders could reintroduce cwd drift if they call lower layers without passing explicit paths.

---

## D. I did not find a live blocker in `build_target` / `workspace_ref`

I checked the next-layer suspects you named.

### `build_target`
- still resolved relative to `workspace_root` in `run_executor`
- because `workspace_root` is now canonical on the main CLI path, this is acceptable
- it is user-specified task content, not a persisted provenance path invariant

### `workspace_ref`
- still exists on `TaskAttemptRecord`
- currently not populated by `run_executor`
- so I do not see a live drift bug there today

These are worth watching, but I did not find a blocker-class issue there in this round.

---

## 5) End-to-end walkthrough: “OpenClaw user invokes Crucible”

## What now works

### Fresh run
1. OpenClaw tool / CLI starts a run
2. `workspace_root` is canonicalized up front
3. `runs_root` / `run_root` are made absolute
4. manifest persists both
5. run executes and event stream reflects the same canonical workspace root

### Resume of an old run without `workspace_root`
1. user provides `--workspace-root` or `CRUCIBLE_WORKSPACE_ROOT`
2. `cmd_resume()` canonicalizes it via `_canonicalize_workspace()`
3. manifest is pinned to that canonical path
4. executor receives the same path
5. `orchestrator_started.payload.workspace_root` matches the manifest

That was the core Round-7 gap, and it is fixed.

## What still breaks the OpenClaw production story

The OpenClaw wrapper’s `resume` response is still incomplete relative to its own contract.

So the real end-to-end story is:
- run: okay
- status/watch: okay **if caller keeps the right runs dir**
- resume: execution itself is okay, **but the OpenClaw machine response is still contract-broken**

That is why I am not willing to call this production-ready yet.

---

## 6) Final recommendation

### Must fix before calling this READY / READY WITH CONDITIONS

1. **Fix `openclaw_tool` resume to always return `run_root`**
   - either emit it from CLI resume events
   - or load it from the manifest after resume
2. **Add tests**
   - `resume` on terminal run returns `run_root`
   - `resume` on non-terminal run returns `run_root`

### Strongly recommended documentation / hardening

3. **Document relative runs-dir semantics explicitly**
   - relative `CRUCIBLE_RUNS_DIR` is anchored to invocation cwd
   - later commands must reuse the same runs dir
   - production embedders should prefer absolute runs dirs
4. **Decide whether `run_root` should also be canonicalized via `realpath()`**
   - not required for correctness today
   - but currently the system-wide invariant is only “absolute,” not “canonical”

If item 1 is fixed cleanly and the tests are added, I would likely move this to **READY WITH CONDITIONS**.
Right now: **NOT READY**.
