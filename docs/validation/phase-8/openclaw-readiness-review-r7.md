# Verdict: NOT READY

Commit reviewed: `40846aa`

Round-6 fixed the exact blocker from Round 6. The new workspace canonicalization is real, the targeted tests pass, and the full suite is green at **531 passed**.

But after re-reviewing the next layer, I found **two remaining provenance blockers**:

1. **`resume` still mishandles `CRUCIBLE_WORKSPACE_ROOT` on first pin of an old run.**
   - In the old-run path, the env var is only `abspath()`'d before execution, not `_canonicalize_workspace()`'d.
   - Result: the manifest gets canonicalized to the real path, but the actual resumed execution/event stream can still use the symlink spelling.
   - That recreates the exact class of inconsistency this review series has been trying to eliminate: **manifest says A, execution record says B**.

2. **`run_root` is still persisted/emitted as a relative path when `--runs-dir` or `CRUCIBLE_RUNS_DIR` is relative.**
   - So the answer to “are all paths in the manifest absolute now?” is **no**.
   - This also leaks through the OpenClaw tool path: `run_root` returned to the caller can still be relative/cwd-sensitive.

Because the bar here is production-readiness and the instruction is “if you find ANY new blocker, NOT READY,” the verdict stays **NOT READY**.

---

## 1) Test pack state

Re-ran the relevant tests:

```bash
uv run pytest tests/runtime/test_workspace_canonical.py tests/runtime/test_workspace_provenance.py tests/runtime/test_lock_and_compat.py tests/runtime/test_resume_incremental.py -q
```

Result:

```text
25 passed in 1.60s
```

Re-ran the full suite:

```bash
uv run pytest -q
```

Result:

```text
531 passed in 9.79s
```

So this is not a “tests are red” problem. It is a remaining invariant/provenance problem.

---

## 2) Round-6 fix re-verification

## A. `create_run_store()` now canonicalizes `workspace_root`

Confirmed in code:
- `src/crucible/runtime/run_store.py:550-586`
- `workspace_root=_canonicalize_workspace(workspace_root)`

Probe result:
- input: relative workspace path
- stored manifest path: absolute/canonical
- verdict: **fixed**

## B. `RunStore.write_manifest()` canonicalizes before write

Confirmed in code:
- `src/crucible/runtime/run_store.py:325-330`

This closes the “direct manifest write stores relative workspace_root verbatim” hole from Round 6.

Verdict: **fixed**

## C. `RunStore.read_manifest()` canonicalizes on read and persists back

Confirmed in code:
- `src/crucible/runtime/run_store.py:332-349`

Probe result:
- hand-crafted `run.json` with `"workspace_root": "relative/ws"`
- first `read_manifest()` returned an absolute canonical path
- `run.json` on disk was rewritten to the canonical absolute path
- second `read_manifest()` was stable/idempotent

Verdict: **fixed**

## D. Symlinked workspace override is now accepted

Confirmed by test and probe:
- `tests/runtime/test_workspace_canonical.py`
- `resume --workspace-root <symlink>` against a run pinned to the real directory returned `0`

Verdict: **fixed**

## E. Trailing slash override is accepted

Probe result:
- `resume --workspace-root /path/to/ws/` matched a manifest pinned to `/path/to/ws`
- returned `0`

Verdict: **fixed**

## F. `..` path components are normalized correctly

`_canonicalize_workspace()` uses:
- `os.path.abspath(...)`
- then `os.path.realpath(...)`

Probe result:
- input: `../ws`
- canonical output matched the resolved absolute path exactly

Verdict: **good**

## G. What happens if a symlink target does not exist?

Probe result:
- `_canonicalize_workspace()` resolves a broken symlink to the target path spelling
- the resulting path is absolute but does not exist

That is acceptable as a storage invariant. If execution later uses it, the run fails honestly because the cwd is missing.

Verdict: **acceptable**

---

## 3) New blockers

## [BLOCKER 1] Old-run resume via `CRUCIBLE_WORKSPACE_ROOT` is still not fully canonicalized

### Why this matters

The round’s stated goal is that the workspace provenance is canonical and durable across all supported entry points.

That is **not** true yet for this path:
- old run has no `workspace_root` in the manifest
- user resumes via env var `CRUCIBLE_WORKSPACE_ROOT`
- env var points at a symlinked workspace path

### Relevant code

In `cmd_run()`, the env var path is canonicalized correctly:
- `src/crucible/runtime/cli.py:116-123`

But in `cmd_resume()`’s old-run branch:
- `src/crucible/runtime/cli.py:377-390`

it does this:

```python
workspace_root = cli_override or os.environ.get("CRUCIBLE_WORKSPACE_ROOT")
...
workspace_root = os.path.abspath(workspace_root)
manifest.workspace_root = workspace_root
store.write_manifest(manifest)
```

So the env var path is only `abspath()`'d before execution, not `_canonicalize_workspace()`'d.

Then `execute_run()` does this:
- `src/crucible/runtime/run_executor.py:67-68`

```python
workspace_root = os.path.abspath(workspace_root or os.getcwd())
store.append_event("orchestrator_started", payload={"workspace_root": workspace_root})
```

### Reproduction

I created:
- an old run with empty `workspace_root`
- a real workspace directory
- a symlink pointing to that directory
- resumed using `CRUCIBLE_WORKSPACE_ROOT=<symlink>`

Observed:

```json
{
  "rc": 0,
  "manifest_workspace_root": "/private/var/.../env_real",
  "orchestrator_workspace_root": "/var/.../env_link",
  "equal": false
}
```

So on the very first resume:
- manifest is pinned to the canonical realpath
- event stream says execution happened in the symlink spelling

That is exactly the same provenance inconsistency the round-5 guard was supposed to prevent, just through a different supported input channel.

### Why this is a blocker

The contract here is not just “resume succeeds.” It is “the persisted run record truthfully identifies the workspace used.”

Right now, for env-var-driven first resume of an old run, the persisted record is internally inconsistent:
- manifest says canonical realpath
- `orchestrator_started` event says symlink path

That is not production-grade provenance.

### Required fix

Use the same canonicalization path everywhere:
- canonicalize `CRUCIBLE_WORKSPACE_ROOT` with `_canonicalize_workspace()` in `cmd_resume()` before both comparison/persist **and** execution
- ideally canonicalize again in `execute_run()` too, so the event payload cannot drift from the manifest spelling

Also add a regression test for:
- old run with empty manifest workspace
- resume via env var symlink path
- assert manifest and `orchestrator_started.payload.workspace_root` match exactly

---

## [BLOCKER 2] `run_root` is still relative/cwd-sensitive when `runs_root` is relative

### Why this matters

One of the explicit review questions was whether **all paths in the manifest are absolute after this fix**.

Answer: **no**.

`workspace_root` is now canonicalized. `run_root` is not.

### Relevant code

`create_run_store()` computes and persists `run_root` like this:
- `src/crucible/runtime/run_store.py:566-575`

```python
if runs_root is None:
    runs_root = default_runs_root()
run_root = os.path.join(runs_root, run_id)
store = RunStore(run_root)
...
run_root=run_root,
```

`RunStore.__init__()` immediately canonicalizes its own internal path:
- `src/crucible/runtime/run_store.py:232`

```python
self._run_root = os.path.abspath(run_root)
```

So the system already has **two different truths**:
- `store.run_root` is absolute
- `manifest.run_root` may still be relative

And `cmd_run()` emits the manifest value to callers:
- `src/crucible/runtime/cli.py:139-144`

```python
_emit_jsonl({
    "event": "run_started",
    "run_id": manifest.run_id,
    "run_root": manifest.run_root,
})
```

### Reproduction

I ran a valid Crucible invocation through the OpenClaw tool path with:
- absolute `workspace_root`
- **relative** `runs_dir='relruns'`

Observed tool output:

```json
{
  "run_root": "relruns/run-b3fb4e4f4327",
  "is_abs": false,
  "status": "ok",
  "exit_code": 0
}
```

And from a direct store probe:

```json
{
  "manifest_run_root": "relative-runs/run-d64be41e2d38",
  "is_abs": false,
  "store_run_root": "/Users/millieclaw/Projects/crucible/relative-runs/run-d64be41e2d38",
  "store_is_abs": true
}
```

So the run store exists in an absolute location, but the manifest and caller-visible `run_root` can still be relative.

### Why this is a blocker

This is the same durability problem in a different field:
- a manifest path field still depends on caller cwd
- OpenClaw callers can receive a relative `run_root` even though the actual run directory is absolute
- the run record is not fully self-describing/portable

If the stated production claim is “durable run store with stable paths,” this is not there yet.

### Required fix

Make `run_root` absolute/canonical at creation time.

Concrete options:
- canonicalize `runs_root` up front and derive `run_root` from that
- or set `manifest.run_root = store.run_root`
- and normalize `default_runs_root()` / `CRUCIBLE_RUNS_DIR` / `--runs-dir` the same way

Also add regression tests for:
- CLI `run --runs-dir relruns`
- env `CRUCIBLE_RUNS_DIR=relruns`
- OpenClaw tool `runs_dir='relruns'`
- assert persisted and emitted `run_root` is absolute

---

## 4) Other review questions

## A. Are there any other manifest paths with similar drift risk?

The one I found is `run_root`.

I did **not** find a comparable path-drift issue in:
- `embedding_session_ref`
- `embedding_surface`
- `project_id`
- `build_id`
- `ledger_ref`

Those are not being used as filesystem paths in the runtime path I reviewed.

If `ledger_ref` later becomes path-like, it should get the same treatment. Right now it is just an opaque string.

## B. Are there direct manifest-construction paths that bypass the workspace canonicalization?

In-tree production code appears clean on this point:
- `RunManifest(...)` construction in `src/` is via `create_run_store()`
- `RunStore.write_manifest()` itself canonicalizes `workspace_root`

So for `workspace_root`, there is **not** an in-tree bypass left if callers go through `write_manifest()`.

For `run_root`, though, there is no equivalent normalization guard.

## C. Trailing spaces and Unicode normalization

I probed both.

### Trailing space

Behavior:
- preserved verbatim
- not trimmed

That is probably fine. A trailing space is a distinct filesystem path on POSIX. This is more “user typo remains a typo” than a provenance bug.

### Unicode normalization

Behavior on this host:
- visually identical NFC/NFD spellings canonicalize to **different strings**
- example: `café` vs `café`

I am **not** calling this a blocker because I did not find a normal Crucible flow that rewrites path normalization behind the user’s back. But it is worth knowing:
- there is no Unicode normalization layer here
- cross-surface/path-string comparison could still false-mismatch on normalization edge cases

If this needs to be robust across manually entered paths from multiple sources, add an explicit normalization policy. Otherwise document that path matching is byte/string exact after filesystem canonicalization.

---

## 5) End-to-end OpenClaw walkthrough

## What works now

I re-ran the real OpenClaw tool path with:
- a valid plan
- absolute `workspace_root`
- absolute `runs_dir`

Observed:
- run started successfully
- returned `status: ok`
- returned absolute `run_root`
- terminal status was `complete`

So the normal “OpenClaw asks Crucible to verify artifacts in a known workspace” path is materially working.

Given the previous rounds, the following are also now in good shape:
- resume no longer forgets `workspace_root`
- mismatched `resume --workspace-root` is rejected
- matching symlink/trailing-slash override is accepted
- old runs can be pinned on first resume
- the old `cmd_resume()` lock leaks are fixed
- read-time manifest repair closes the Round-6 relative-workspace regression

## What still breaks the production story

Two end-to-end provenance edges are still wrong:

1. **Old run resumed via env var workspace path**
   - supported input channel
   - can produce manifest/event disagreement on workspace identity

2. **Relative runs dir**
   - supported input channel (`--runs-dir`, `CRUCIBLE_RUNS_DIR`, OpenClaw tool `runs_dir`)
   - can produce relative `run_root` in manifest and tool output

That means the OpenClaw user story is not yet fully durable/self-describing across all supported ways of invoking the runtime.

---

## 6) Final recommendation

**NOT READY**.

Round-6’s actual fix is good. But I would require one more cleanup pass before production signoff:

1. **Canonicalize env-var workspace pinning in `cmd_resume()`**
   - use `_canonicalize_workspace()` for `CRUCIBLE_WORKSPACE_ROOT` in the old-run branch
   - pass the canonical path into `execute_run()`
   - preferably canonicalize again in `execute_run()` before emitting `orchestrator_started`

2. **Make `run_root` an absolute/canonical manifest invariant too**
   - canonicalize `runs_root`
   - persist `manifest.run_root` as absolute
   - emit the canonical path to CLI/OpenClaw callers

3. **Add regression coverage for the actual missing surfaces**
   - old-run resume via env-var symlink path
   - relative `--runs-dir`
   - relative `CRUCIBLE_RUNS_DIR`
   - OpenClaw tool invocation with relative `runs_dir`

4. **Optional but worthwhile**
   - decide/document Unicode normalization policy for path comparison

If blockers 1 and 2 are fixed cleanly, I would expect the verdict to move to **READY WITH CONDITIONS** or possibly **READY**. But as of `40846aa`, there are still supported invocation paths where the durable run record is not internally consistent.
