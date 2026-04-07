# Verdict: NOT READY

Commit reviewed: `0b60b23`

Round-5’s stated fixes are real:
- mismatched `resume --workspace-root` is now rejected
- matching override is accepted
- old runs can be pinned on first resume, and later resumes must match
- the two `cmd_resume()` early-return lock leaks are fixed
- the manifest write used to pin an old run happens while the run lock is held
- full suite is green: **521 passed**

But I found one remaining provenance bug that is serious enough to keep this at **NOT READY**:

> **`workspace_root` is still not enforced as an absolute/canonical manifest invariant.**
>
> If a manifest contains a relative `workspace_root`, `resume` becomes cwd-sensitive again. The persisted run record is no longer sufficient to reproduce what directory the verification will actually run in. That is the same class of durability/provenance failure we have been chasing for five rounds.

The current CLI writes absolute paths, so the happy path is fine. The store/manifest layer still does not enforce that invariant, though, and `create_run_store()` will happily persist a relative path verbatim.

---

## 1) Test pack state

Targeted new tests pass:

```bash
$ uv run pytest tests/runtime/test_workspace_provenance.py -q
....                                                                     [100%]
4 passed in 0.17s

$ uv run pytest tests/runtime/test_lock_and_compat.py -q
........                                                                 [100%]
8 passed in 1.28s
```

Full suite also passes:

```bash
$ uv run pytest -q
........................................................................ [ 13%]
........................................................................ [ 27%]
........................................................................ [ 41%]
........................................................................ [ 55%]
........................................................................ [ 69%]
........................................................................ [ 82%]
........................................................................ [ 96%]
.................                                                        [100%]
521 passed in 9.46s
```

---

## 2) Round-5 fix re-verification

## A. Mismatched `--workspace-root` on a pinned run is rejected

Observed:

```text
RC: 1
STDERR:
--workspace-root /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-workspace-veomom3g/ws_b does not match the run's persisted workspace_root /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-workspace-veomom3g/ws_a. Refusing to resume to avoid manifest/execution inconsistency.
```

Manifest stayed pinned to `ws_a`:

```json
{
  "run_id": "run-c191fe1e3f59",
  "current_phase": "intake",
  "current_status": "running",
  "workspace_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-workspace-veomom3g/ws_a"
}
```

Verdict: **fixed**.

## B. Matching override is accepted

I also checked a trailing-slash form while I was here.

```text
RC: 0
STDOUT:
resumed run run-eb374d6c2e3e
reconciled 0 in-flight attempts
terminal_status: complete
```

Verdict: **fixed**.

## C. Old run can be pinned on first resume; later resumes must match

First resume of an old run with no `workspace_root`:

```text
RC: 0
STDOUT:
resumed run run-b61b757d7bb5
reconciled 0 in-flight attempts
terminal_status: complete
```

Manifest after first resume:

```json
{
  "run_id": "run-b61b757d7bb5",
  "current_phase": "done",
  "current_status": "complete",
  "workspace_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-workspace-veomom3g/ws_a"
}
```

After clearing `result.json` to force the validation path again, a later mismatch is rejected:

```text
RC: 1
STDERR:
--workspace-root /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-workspace-veomom3g/ws_b does not match the run's persisted workspace_root /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-workspace-veomom3g/ws_a. Refusing to resume to avoid manifest/execution inconsistency.
```

Verdict: **fixed**.

---

## 3) Lock leak re-verification

These bugs only matter if `cmd_resume()` is called in-process, so I verified them that way and then tried to reacquire the lock from a fresh `RunStore` instance.

## A. Already-terminal run

Observed `cmd_resume()` output:

```text
returncode: 0
stdout: already terminal: complete
stderr:
```

Post-return lock state:

```text
releasable_after_terminal: true
```

Verdict: **fixed**. The old early-return leak is gone.

## B. Missing plan/manifest

Observed `cmd_resume()` output after deleting `tasks.json`:

```text
returncode: 5
stdout:
stderr: run run-f4962be82ffc is missing plan or manifest
```

Post-return lock state:

```text
releasable_after_missing: true
```

Verdict: **fixed**. The second early-return leak is also gone.

---

## 4) Did the new manifest write during resume hold the lock correctly?

Yes.

I created an old run with no `workspace_root`, resumed it with `--workspace-root`, and used a sleeping verification command so I could inspect the run while the first resume was still active.

What I observed:
- `run.json` was already updated with the new `workspace_root`
- the first resume process was still running
- a second concurrent `resume` got `lock busy`

Output from the concurrent resume:

```text
RC: 5
STDERR:
run run-93dde9f73b09 is already locked by another process
```

And the probe confirmed the pin had already happened while the first process still held the lock:

```text
pinned_seen_while_running: true
```

Verdict: **good**. The old-run pin write is happening under the run lock.

---

## 5) New blockers / new findings

## [BLOCKER] Relative `workspace_root` in the manifest is still unsafe

This is the one that keeps the verdict at **NOT READY**.

Relevant code path:
- `create_run_store()` persists `workspace_root` exactly as given (`src/crucible/runtime/run_store.py:527-552`)
- `cmd_resume()` uses `manifest.workspace_root` as authoritative if present (`src/crucible/runtime/cli.py:363-373`)
- `execute_run()` then does `os.path.abspath(workspace_root or os.getcwd())` (`src/crucible/runtime/run_executor.py:67`)

That means a manifest containing:

```json
"workspace_root": "relws"
```

is **not actually durable**. Its effective execution directory depends on the caller’s current working directory at resume time.

I reproduced that directly.

Persisted manifest:

```json
{
  "run_id": "run-4fc2d3d04b72",
  "current_phase": "done",
  "current_status": "failed",
  "workspace_root": "relws"
}
```

Resume output:

```text
RC: 3
STDOUT:
resumed run run-4fc2d3d04b72
reconciled 0 in-flight attempts
terminal_status: failed
```

Recorded failure reason:

```text
criterion c1 failed: command exited 127: [Errno 2] No such file or directory: '/private/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-paths-g2xclsd1/relws'
```

The intended workspace actually existed at `.../relative/relws`; the run failed because the relative path was reinterpreted against the resume caller’s cwd.

Why this matters:
- the manifest is supposed to be the durable source of truth
- with a relative `workspace_root`, it is not
- cwd has become part of the hidden execution contract again

This is the same class of provenance bug as before, just in a narrower shape.

### Required fix

At minimum, enforce one invariant everywhere:
- `workspace_root` stored in the manifest must be absolute

Concrete options:
1. normalize in `create_run_store()` before persisting
2. normalize legacy manifests on load/resume before compare/use
3. reject relative `manifest.workspace_root` with a clear error instead of silently reinterpreting it

If symlink-stable identity matters, decide whether the invariant is:
- absolute lexical path (`abspath`), or
- canonical filesystem path (`realpath` / `Path.resolve(strict=False)`)

Right now it is neither enforced nor documented.

---

## 6) Answers to the specific “look for regressions” questions

## A. Any other manifest-drift surfaces like `embedding_session_ref`, `project_id`, `build_id`?

Not through the current resume surface.

CLI parser:

```python
p_resume.add_argument("run_id")
p_resume.add_argument("--jsonl", action="store_true")
p_resume.add_argument("--workspace-root", default=None, ...)
```

Observed in `src/crucible/runtime/cli.py:452-456`.

There is **no** resume-time override flag for:
- `project_id`
- `build_id`
- `embedding_session_ref`
- `embedding_surface`

And the OpenClaw tool’s resume path likewise only forwards `run_id` plus env/args for workspace selection, not those other manifest fields (`src/crucible/runtime/openclaw_tool.py:239-252`).

So the round-5 provenance fix does **not** leave a sibling hole for those fields.

Verdict: **good**.

## B. Backend identity: still a real concern?

Yes, but not the blocker I am hanging this round on.

Still true:
- `cmd_run()` hardcodes `LocalShellAdapter()` (`src/crucible/runtime/cli.py:178-181`)
- `cmd_resume()` hardcodes `LocalShellAdapter()` (`src/crucible/runtime/cli.py:345-348`)
- `RunManifest` still has no backend identity field (`src/crucible/runtime/run_store.py:38-52`)

So backend-agnostic resume is still not real.

For the **currently shipped user path**, this is partly masked because the OpenClaw tool shells out to the CLI and the skill is explicit that the standalone path is a verifier using `LocalShellAdapter`, not a true builder (`skills/openclaw/SKILL.md:9-16`).

Verdict: **still a real architecture limitation, but not today’s new blocker**.

## C. What if `manifest.workspace_root` no longer exists?

This is materially honest.

Observed:

```text
RC: 3
STDOUT:
resumed run run-ea97e8ccf5ba
reconciled 0 in-flight attempts
terminal_status: failed
```

The recorded blocker is explicit:

```text
criterion c1 failed: command exited 127: [Errno 2] No such file or directory: '/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-missing-ws-agdhsq08/gone'
```

Not pretty, but honest enough.

Verdict: **acceptable**.

## D. Symlinks / trailing slashes / relative paths

- **Trailing slash:** okay
  - `--workspace-root /path/to/ws/` matched a manifest pinned to `/path/to/ws`
  - resume succeeded

- **Symlink vs realpath:** currently a false-negative mismatch
  - manifest pinned to `/tmp/link_ws`
  - resume with `/tmp/real_ws` was rejected even though they point to the same directory

  Observed:

  ```text
  RC: 1
  STDERR:
  --workspace-root /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-paths-g2xclsd1/real_ws does not match the run's persisted workspace_root /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-paths-g2xclsd1/link_ws. Refusing to resume to avoid manifest/execution inconsistency.
  ```

  This is **safe but annoying**.

- **Relative manifest path:** **unsafe blocker**
  - see section 5 above

---

## 7) End-to-end walkthrough: can an OpenClaw user actually use this now?

## What works

I re-ran the real OpenClaw tool path with a workspace containing `artifact.txt` and a verification command `test -f artifact.txt && echo E2E_OK`.

Tool result:

```json
{
  "exit_code": 0,
  "status": "ok",
  "run_id": "run-6d5437638e16",
  "run_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r6-e2e-4bimcqep/runs/run-6d5437638e16",
  "terminal_status": "complete",
  "completed_tasks": ["t1"],
  "failed_tasks": [],
  "partial_tasks": [],
  "blocked_reason": "",
  "total_runtime_seconds": 0.003972768783569336
}
```

`status` looked healthy:
- manifest persisted
- result persisted
- `event_count: 8`
- one winning attempt record
- `is_terminal: true`

`watch --jsonl --from 0` replayed the expected event sequence:
- `run_started`
- `orchestrator_started`
- `tasks_loaded`
- `task_dispatched`
- `criterion_dispatched`
- `criterion_passed`
- `task_completed`
- `run_terminal`

Resuming the already-terminal run returned cleanly:

```text
RC: 0
STDOUT:
already terminal: complete
```

## What it still is, and is not

This is now materially usable as a **durable verifier**.

It is still **not** a full backend-agnostic OpenClaw build runtime:
- the default CLI path is still `LocalShellAdapter`
- the skill itself says build is out of scope for the standalone verifier path
- true backend identity / backend restoration is still not persisted

So the user story I would sign off today is:
- “I already have artifacts or can arrange for them to exist in a known workspace”
- “Use Crucible to verify them durably, persist audit artifacts, inspect status/watch, and resume safely”

That story is close.
But because the manifest layer still allows a relative `workspace_root` to make resume cwd-sensitive again, I am not calling it ready.

---

## 8) Final recommendation

**NOT READY**.

Round-5 fixed the blocker it was meant to fix, and it fixed the in-process lock leaks too. Good.

But I would require one more cleanup before signoff:

1. **Enforce `workspace_root` as an absolute persisted invariant**
   - normalize before writing manifests
   - normalize or reject on load/resume
   - do not let relative manifest paths reintroduce cwd-sensitive resume behavior

2. **Choose a symlink policy**
   - if path identity is lexical, document it
   - if path identity is physical, compare canonicalized paths instead of raw strings

3. **Optional but still worth doing:** persist backend identity if backend-agnostic resume is actually part of the intended contract

If item 1 is fixed cleanly, I think this moves to **READY WITH CONDITIONS**.
Right now, one provenance edge still undermines the durability story, so: **NOT READY**.
