# Verdict: NOT READY

Round 4’s stated fixes are **real**:
- concurrent `resume` no longer crashes with a traceback in the normal CLI path
- old manifests load
- future manifests with unknown fields load
- `resume` now refuses to fall back to ambient cwd when `workspace_root` is missing

But the next layer exposed a **new integrity blocker**:

1. **`resume --workspace-root` can silently rebind a run to a different workspace than the one recorded in `run.json`.**
   - `cmd_resume()` prefers the CLI override over the persisted manifest (`src/crucible/runtime/cli.py:352-355`)
   - `execute_run()` then executes verification in that override directory and records it in `orchestrator_started.payload.workspace_root` (`src/crucible/runtime/run_executor.py:67-69`)
   - **but the manifest stays on the old workspace path**
   - result: the durable run record can say “this run was for workspace A” while the successful verification actually ran in workspace B

That is a provenance hole, not a cosmetic quirk. For a durability-focused OpenClaw verifier, that keeps this at **NOT READY**.

---

## Repo / test pack state

Observed on commit:

```bash
$ git rev-parse --short HEAD
8b6e999
```

Claimed test count is real:

```bash
$ uv run pytest tests/runtime/test_lock_and_compat.py -q
........                                                                 [100%]
8 passed in 1.18s

$ uv run pytest -q
........................................................................ [ 13%]
........................................................................ [ 27%]
........................................................................ [ 41%]
........................................................................ [ 55%]
........................................................................ [ 69%]
........................................................................ [ 83%]
........................................................................ [ 97%]
.............                                                            [100%]
517 passed in 9.46s
```

---

## Round-4 blocker re-verification

## 1) Concurrent `resume` race: fixed in the CLI path

Relevant code is now present:
- unique temp files for atomic writes: `src/crucible/runtime/run_store.py:194-213`
- advisory per-run lock: `src/crucible/runtime/run_store.py:243-285`
- `cmd_run()` acquires the lock: `src/crucible/runtime/cli.py:183-198`
- `cmd_resume()` acquires the lock: `src/crucible/runtime/cli.py:313-375`

I spawned two overlapping `crucible resume` processes against the same unfinished run, with the first one holding the lock long enough to force contention.

Observed output:

```text
lock_path: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r5-concurrent-2cj5308j/runs/run-50e12441b9d4/run.lock
lock_seen_while_running: true

RESUME #1 RC: 0
RESUME #1 STDOUT:
resumed run run-50e12441b9d4
reconciled 0 in-flight attempts
terminal_status: complete
RESUME #1 STDERR:

RESUME #2 RC: 5
RESUME #2 STDOUT:
RESUME #2 STDERR:
run run-50e12441b9d4 is already locked by another process
```

Checks:
- no traceback from either process
- one succeeds, one exits 5 with `lock` in stderr
- lock file exists during execution
- `run.json` still parses cleanly afterward

Post-run `run.json`:

```json
{
  "run_id": "run-50e12441b9d4",
  "project_id": "p",
  "build_id": "b",
  "run_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r5-concurrent-2cj5308j/runs/run-50e12441b9d4",
  "created_at": 1775536288.980982,
  "spec_text_hash": "2d711642b726b044",
  "task_definitions_hash": "d8a217f25e4276f6",
  "current_phase": "done",
  "current_status": "complete",
  "cli_version": "0.1.0",
  "embedding_surface": "",
  "embedding_session_ref": "",
  "ledger_ref": "",
  "workspace_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r5-concurrent-2cj5308j/ws"
}
```

Verdict: **the Round-4 concurrent-resume blocker is fixed for the normal CLI subprocess path.**

Note: the file is named **`run.lock`**, not `.run.lock`.

---

## 2) Backward compat: fixed as claimed

### A. Old manifest without `workspace_root` loads

`RunManifest.from_dict()` now filters unknown keys and lets dataclass defaults fill missing ones (`src/crucible/runtime/run_store.py:57-65`).

Observed loaded manifest:

```json
{
  "run_id": "run-b4cd081838fa",
  "project_id": "p",
  "build_id": "b",
  "run_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r5-compat-bb5w5opi/runs/run-b4cd081838fa",
  "created_at": 1775536291.023438,
  "spec_text_hash": "2d711642b726b044",
  "task_definitions_hash": "cfa054c453bf66f2",
  "current_phase": "intake",
  "current_status": "running",
  "cli_version": "0.1.0",
  "embedding_surface": "",
  "embedding_session_ref": "",
  "ledger_ref": "",
  "workspace_root": ""
}
```

### B. Future manifest with unknown fields loads

Observed loaded manifest from a hand-crafted future schema:

```json
{
  "run_id": "run-future",
  "project_id": "p",
  "build_id": "b",
  "run_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r5-compat-bb5w5opi/future-run",
  "created_at": 1775536291.086091,
  "spec_text_hash": "abc",
  "task_definitions_hash": "def",
  "current_phase": "intake",
  "current_status": "running",
  "cli_version": "999",
  "embedding_surface": "",
  "embedding_session_ref": "",
  "ledger_ref": "",
  "workspace_root": "/tmp/work"
}
```

### C. Resume of old run without override now refuses correctly

Observed output:

```text
RC: 1
STDERR:
run run-b4cd081838fa was created without workspace_root and no --workspace-root override was provided. Refusing to resume in ambient cwd (/Users/millieclaw/Projects/crucible). Pass --workspace-root explicitly.
```

### D. Resume of old run with explicit `--workspace-root` succeeds

Observed output:

```text
RC: 0
STDOUT:
resumed run run-b4cd081838fa
reconciled 0 in-flight attempts
terminal_status: complete
STDERR:
```

Verdict: **the Round-4 backward-compat gap identified in R4 is fixed as specified.**

---

## New blockers / next-layer findings

## 1) [BLOCKER] `resume --workspace-root` can corrupt provenance for an existing run

This is the real release blocker.

Current behavior:
- `cmd_resume()` accepts `--workspace-root` for **all** runs, not just old manifests (`src/crucible/runtime/cli.py:352-355, 427-431`)
- it does **not** verify that the override matches `manifest.workspace_root`
- it does **not** update the manifest if a different workspace is used
- `execute_run()` records the actual runtime workspace only in the event stream (`src/crucible/runtime/run_executor.py:67-69`)

So one run can have:
- `run.json.workspace_root = ws_a`
- actual resumed verification executed in `ws_b`
- final `result.json = complete`

I reproduced exactly that.

Control run, no override, manifest says `ws_a`, required file exists only in `ws_b`:

```text
CONTROL RESUME RC: 3
CONTROL STDOUT:
resumed run run-8601d94177b4
reconciled 0 in-flight attempts
terminal_status: failed
```

Now same logical run setup, but resume with `--workspace-root ws_b`:

```text
OVERRIDE RESUME RC: 0
OVERRIDE STDOUT:
resumed run run-3b48b6e9ad18
reconciled 0 in-flight attempts
terminal_status: complete
```

Manifest before resume:

```json
{
  "run_id": "run-3b48b6e9ad18",
  "current_phase": "intake",
  "current_status": "running",
  "workspace_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r5-mismatch-9ecc2sx5/ws_a"
}
```

Manifest after successful resume:

```json
{
  "run_id": "run-3b48b6e9ad18",
  "current_phase": "done",
  "current_status": "complete",
  "workspace_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r5-mismatch-9ecc2sx5/ws_a"
}
```

But the event log proves the actual verification ran in `ws_b`:

```json
{
  "workspace_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r5-mismatch-9ecc2sx5/ws_b"
}
```

Why this matters:
- a user/operator can accidentally resume against the wrong checkout
- the run then emits a clean success result
- the durable manifest still points at the original workspace
- later audits read conflicting truths from manifest vs events

That is exactly the kind of state ambiguity this durability layer is supposed to prevent.

**Required fix before signoff:**
- only allow `--workspace-root` override when `manifest.workspace_root` is empty, or
- require an explicit destructive flag like `--force-workspace-root-change`, and if used:
  - persist the new workspace in manifest,
  - append an explicit audit event recording old → new,
  - probably mark the run as migrated / resumed-with-override.

As shipped, this is **NOT READY**.

---

## 2) Lock cleanup after `kill -9`: not held forever, but stale file remains

This part is okay.

Observed output:

```text
lock_seen_before_kill: true
killed_proc_returncode: -9
lock_file_exists_after_kill: true
lock_file_contents_after_kill: 30901

RESUME AFTER KILL-9 RC: 0
RESUME AFTER KILL-9 STDOUT:
resumed run run-06024f5290eb
reconciled 0 in-flight attempts
terminal_status: complete
```

Interpretation:
- `fcntl.flock` releases on process death, so the lock is **not held forever**
- the `run.lock` file itself stays on disk with a stale PID string

Verdict: **not a blocker**, but mildly confusing operationally. The stale PID file is only advisory/debug info.

---

## 3) Lock file in run dir does not break `watch` / `status`

This looks fine.

Why:
- `watch` reads only `events.jsonl` via `read_events()` (`src/crucible/runtime/run_store.py:379-412`)
- `status` reads explicit files (`run.json`, `result.json`, `events.jsonl`, `attempts/*.json`) and does not directory-scan arbitrary files for event parsing
- a persistent `run.lock` file coexists harmlessly in the run directory

I also re-ran normal `status` and `watch` on completed runs after the new locking work; both behaved normally.

Verdict: **not a blocker**.

---

## 4) Other single-writer surfaces: mostly okay in current CLI path, still loose in bridge path

### Current shipped CLI path
For normal `crucible run` / `crucible resume`:
- the run lock is held across `execute_run()`
- manifest/result/attempt writes are serialized
- `events.jsonl` appends come from the lock holder only

So for the currently shipped subprocess CLI path, the single-writer story is materially okay.

### Bridge / adapter path
There is still an unprotected surface in the event-backed adapter path:
- `OpenClawSubagentAdapter.spawn()` writes adapter state + adapter log (`src/crucible/runtime/openclaw_adapter.py:108-145`)
- `kill()` mutates the same adapter-state file (`src/crucible/runtime/openclaw_adapter.py:186-200`)
- `ingest_event()` also rewrites adapter state (`src/crucible/runtime/openclaw_adapter.py:204-220+`)
- none of those acquire the run lock

Because `_atomic_write_json()` now uses unique temp files, these writes are unlikely to corrupt JSON on disk. But there is still **logical last-write-wins race potential** if kill/progress/terminal events land concurrently.

Verdict: **not the blocker for the current default CLI/tool path**, but still a gap if they want the OpenClaw bridge path to be first-class and durable.

---

## 5) NFS / remote-FS caveat

The lock implementation is `fcntl.flock` (`src/crucible/runtime/run_store.py:247-279`).

That is fine on normal local macOS/Linux filesystems.
It is **not something I would trust blindly on NFS/SMB/network-mounted workspaces** without explicit support/testing; advisory lock semantics vary by mount type and server config.

Verdict: **condition / documentation caveat**, not today’s release blocker.

---

## 6) Backend identity is still not persisted; `resume` still hardcodes `LocalShellAdapter`

This is still real.

`cmd_run()` and `cmd_resume()` both instantiate `LocalShellAdapter` directly:
- `src/crucible/runtime/cli.py:175-181`
- `src/crucible/runtime/cli.py:343-346`

So CLI durability faithfully resumes only **CLI-created local-shell runs**.
If a host/embedding layer created a run using a different backend contract, generic CLI `resume` still would not know how to rehydrate it.

Given the shipped OpenClaw tool wrapper currently shells out to the CLI and therefore also lands on local-shell verification, this is **not the blocker I’m hanging the verdict on**.

But it does mean the system is still narrower than the top-line “sub-agent builds via OpenClaw” framing.

---

## 7) Secondary bug introduced by the lock work: some early-return paths leak the lock in-process

This is not a subprocess CLI blocker, but it is a real bug.

`cmd_resume()` acquires the lock at line 315. But if the run is already terminal, it returns at lines 322-328 **without releasing it**. Same problem exists for the `missing plan or manifest` return path at 339-341.

I reproduced the in-process leak by calling `cmd_resume()` twice in one Python process:

```text
run run-ae8cca99fb34 is already locked by another process
already terminal: complete
RUN_ID=run-ae8cca99fb34
RC1=0
RC2=5
```

That happened because the first `cmd_resume()` returned early on an already-terminal run and left the lock held for the lifetime of the process.

For the normal CLI subprocess path this self-heals on process exit, so it is **not today’s top blocker**. But it is sloppy and will bite any in-process embedding that uses the command functions directly.

Fix: wrap the whole body in `with store:` or move all return paths under a single `try/finally store.release_lock()`.

---

## End-to-end walkthrough: “OpenClaw user invokes Crucible to verify a build”

## What works end-to-end right now

I exercised the shipped OpenClaw tool wrapper path (`crucible.runtime.openclaw_tool.execute`) with a real workspace and verification command.

Observed tool result:

```json
{
  "exit_code": 0,
  "status": "ok",
  "run_id": "run-44f6da50944a",
  "run_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r5-e2e-77fq0103/runs/run-44f6da50944a",
  "terminal_status": "complete",
  "completed_tasks": [
    "t1"
  ],
  "failed_tasks": [],
  "partial_tasks": [],
  "blocked_reason": "",
  "total_runtime_seconds": 0.0039010047912597656
}
```

`status` on the resulting run is healthy and auditably populated:
- manifest persisted
- result persisted
- 8 events in `events.jsonl`
- one successful attempt record

`watch --jsonl --from 0` streamed the expected event sequence:
- `run_started`
- `orchestrator_started`
- `tasks_loaded`
- `task_dispatched`
- `criterion_dispatched`
- `criterion_passed`
- `task_completed`
- `run_terminal`

Resuming the already-terminal run returns cleanly:

```text
RC: 0
STDOUT:
already terminal: complete
```

So the practical user story **“verify an already-built thing, persist the audit trail, inspect status/watch later”** is now real.

---

## Where it still breaks / feels rough

### 1. It is still a verifier, not an end-to-end sub-agent build runtime
The skill is explicit about this, but the top-line framing still oversells it.

From `skills/openclaw/SKILL.md:11-16`:
- build is out of Crucible’s scope
- standalone CLI default is `LocalShellAdapter`
- it only runs verification commands locally
- real OpenClaw sub-agent build plumbing requires extra bridge wiring

So an OpenClaw user who says “use Crucible to build X” does **not** get a built-in sub-agent build loop from the shipped default path. They get a durable verifier around artifacts that already exist or are produced out-of-band.

That is an acceptable architecture choice.
It is not the same thing as a completed OpenClaw-native build harness.

### 2. Workspace provenance is still too easy to falsify
This is the blocker above. A durable verifier cannot let the same run ID silently drift across workspaces.

### 3. CLI durability is subprocess-centric
The happy path is fine because the tool wrapper shells out (`src/crucible/runtime/openclaw_tool.py:149-176`).
But some lock hygiene bugs only stay harmless because each command runs in its own process.

### 4. Backend resume contract is still local-shell-only
Good enough for today’s verifier path.
Not good enough if they want resumed OpenClaw-backed build runs to be truly backend-agnostic.

---

## Final recommendation

**NOT READY**.

Round 4 did fix the issues Round 4 claimed to fix. That part is real.

But before I would sign this off for production OpenClaw readiness, I would require:

1. **Close the workspace override provenance hole**
   - do not allow arbitrary workspace override for a run that already has a persisted `workspace_root`, unless a very explicit migration/force path exists
   - if override is permitted, persist the change and audit it explicitly

2. **Fix lock release on all `cmd_resume()` return paths**
   - current subprocess usage masks this, but the function itself is not safe in-process

3. **Decide and document the backend-resume contract**
   - if resume is CLI/local-shell only, say that bluntly
   - if Phase 8 wants durable backend-agnostic resume, persist backend identity and restore it

4. **Document filesystem assumptions**
   - local POSIX filesystem: yes
   - NFS/network mounts: not guaranteed

If item 1 is fixed cleanly, this likely moves to **READY WITH CONDITIONS**.
If item 1 stays as-is, I would keep it at **NOT READY** because the run record can no longer be trusted as a faithful statement of what was verified.
