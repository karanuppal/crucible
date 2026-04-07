# Verdict: NOT READY

Round 2 fixed the six issues I flagged in the prior review.

That is real:
- the semantic bypass case I asked for now fails honestly
- the bridge is now actually usable from `execute_run()` via `BridgeBackedAdapter`
- `openclaw_tool.execute()` now returns structured output with `run_id`
- `watch --follow` now blocks and can emit events before the run is terminal
- `resume` now skips already-winning work
- the repo really does have **508 passing tests**

But I found a **new production blocker** introduced / left exposed by the round-2 fixes:

> **`resume` forgets the original `workspace_root`, so resumed verification runs in the wrong directory.**

That means an interrupted run can fail forever even after the artifact is fixed in the original workspace, simply because `resume` replays verification in the process cwd instead of the run’s workspace. For a long-running OpenClaw runtime, that is not a paper cut. It breaks the durability contract.

---

## Test pack / repo state

Observed commands:

```bash
$ uv run pytest tests/runtime/test_bridge_executor_integration.py tests/runtime/test_openclaw_tool.py tests/runtime/test_watch_streaming.py tests/runtime/test_resume_incremental.py -q
...........................                                              [100%]
27 passed in 2.28s
```

```bash
$ uv run pytest -q
........................................................................ [ 14%]
........................................................................ [ 28%]
........................................................................ [ 42%]
........................................................................ [ 56%]
........................................................................ [ 70%]
........................................................................ [ 85%]
........................................................................ [ 99%]
....                                                                     [100%]
508 passed in 8.44s
```

So yes: the claimed test improvements are real.

---

## Round-2 issue re-verification

## 1) Semantic bypass blocked

Requested adversarial case:
- `verification_command: "echo PASS_OK"`
- `build_target: "src/nonexistent.py"`
- should fail with exit 3 / terminal_status failed

Observed command:

```bash
$ /Users/millieclaw/Projects/crucible/.venv/bin/python3 -m crucible.runtime.cli \
    --runs-dir /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r3-semantic-nkucshkv/runs \
    run /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r3-semantic-nkucshkv/plan.json \
    --workspace-root /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r3-semantic-nkucshkv
```

Observed output:

```text
EXIT: 3
STDOUT:
run_id: run-242d152afd98
run_root: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r3-semantic-nkucshkv/runs/run-242d152afd98
terminal_status: failed
completed: []
failed: ['t1']
STDERR:
```

Verdict: **fixed**.

Code path matches the claim: `execute_run()` now checks path-like `build_target`s after a nominal pass and flips the criterion to fail if the target is missing (`src/crucible/runtime/run_executor.py:204-232`).

---

## 2) Bridge-backed adapter works inside `execute_run()`

This was the real round-2 question: not whether the bridge exists, but whether the executor can actually consume it.

Observed probe using `SimulatedOpenClawBridge + BridgeBackedAdapter`:

```json
{
  "run_id": "run-63da934cbd74",
  "terminal_status": "complete",
  "completed_tasks": [
    "t1"
  ],
  "failed_tasks": [],
  "partial_tasks": [],
  "blocked_reason": "",
  "integration_status": null,
  "total_runtime_seconds": 0.0012102127075195312,
  "cost_summary": {
    "backends_used": [
      "openclaw-bridge"
    ],
    "total_wall_clock_seconds": 0.0012102127075195312,
    "retries_total": 0,
    "subagents_spawned": 1,
    "estimated_tokens": null,
    "notes": ""
  }
}
```

Verdict: **fixed**.

The new mechanism is real:
- `SessionsSpawnBridge.run_spec_to_completion()` now does spawn → wait → ingest → collect (`src/crucible/runtime/openclaw_bridge.py:190-249`)
- `BridgeBackedAdapter.spawn()` wraps that sync bridge lifecycle behind the executor’s old `spawn()/collect()` contract (`src/crucible/runtime/openclaw_bridge.py:256-320`)

That closes the exact gap I called out in R2.

---

## 3) `openclaw_tool.execute()` now returns structured output with `run_id`

Observed tool output:

```json
{
  "exit_code": 0,
  "status": "ok",
  "run_id": "run-59081f254b27",
  "run_root": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r3-tool-nxiqzgv4/runs/run-59081f254b27",
  "terminal_status": "complete",
  "completed_tasks": [
    "t1"
  ],
  "failed_tasks": [],
  "partial_tasks": [],
  "blocked_reason": "",
  "total_runtime_seconds": 0.003970146179199219
}
```

I also verified the session metadata is threaded into the manifest:

```json
{
  "manifest_embedding_surface": "openclaw-test",
  "manifest_embedding_session_ref": "session-r3-abc"
}
```

Verdict: **fixed**.

The wrapper rewrite is not theater this time:
- it forces `--jsonl` / `--json`
- it parses structured output instead of scraping the last human line
- it threads env for `embedding_surface`, `embedding_session_ref`, and `workspace_root`

Relevant code: `src/crucible/runtime/openclaw_tool.py:53-60`, `149-176`, `179-274`, `277-307`.

---

## 4) `watch --follow` blocks and streams new events

I did **not** just re-run the happy-path test. I checked the property that actually matters: can `watch` emit output while the run is still in progress?

Observed probe:

```json
{
  "first_line_received": true,
  "first_line": "{\"event_id\":\"evt-fb6dd89d58\",\"run_id\":\"run-a12ce52d2b28\",\"timestamp\":1775535059.4934049,\"type\":\"run_started\",\"task_id\":\"\",\"attempt_id\":\"\",\"payload\":{\"run_id\":\"run-a12ce52d2b28\",\"project_id\":\"r3-watch\"}}",
  "watch_still_running_after_first_line": true,
  "watch_elapsed_seconds": 1.886,
  "watch_exit": 0,
  "event_types": [
    "run_started",
    "criterion_passed",
    "task_completed",
    "run_terminal"
  ],
  "run_exit": 0,
  "run_stdout": "run_id: run-a12ce52d2b28\nrun_root: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r3-watch-9gy7lvjw/runs/run-a12ce52d2b28\nterminal_status: complete\ncompleted: ['slow-task']\nfailed: []",
  "run_stderr": "",
  "watch_stderr": ""
}
```

The key part is not the final event list. The key part is:
- first line arrived
- `watch` was **still running after that first line**
- total watch time was ~1.9s, i.e. it blocked through the delayed command

I also checked the full replay against `events.jsonl`; the watch output contained all 8 persisted events for the run.

Verdict: **fixed**.

Relevant code: `src/crucible/runtime/cli.py:243-287`.

---

## 5) `resume` does not re-run completed work

Observed probe using a side-effectful counter command:

```json
{
  "initial_summary": {
    "run_id": "run-ea7f826fe2d4",
    "terminal_status": "complete",
    "completed_tasks": [
      "counter-task"
    ],
    "failed_tasks": [],
    "partial_tasks": [],
    "blocked_reason": "",
    "integration_status": null,
    "total_runtime_seconds": 0.00586390495300293,
    "cost_summary": {
      "backends_used": [
        "local-shell"
      ],
      "total_wall_clock_seconds": 0.005864858627319336,
      "retries_total": 0,
      "subagents_spawned": 1,
      "estimated_tokens": null,
      "notes": ""
    }
  },
  "counter_before_resume": "1",
  "resume_exit": 0,
  "resume_stdout": "resumed run run-ea7f826fe2d4\nreconciled 0 in-flight attempts\nterminal_status: complete",
  "resume_stderr": "",
  "counter_after_resume": "1"
}
```

Verdict: **fixed**.

The counter stayed at `1`, so the winning task was skipped. That is the exact failure mode I called out in R2, and it is gone.

Mechanically this comes from `execute_run()` precomputing winning attempts and skipping those tasks on replay (`src/crucible/runtime/run_executor.py:93-107`).

---

## New blocker found in Round 3

## Blocker: `resume` loses the original workspace and replays verification in the wrong cwd

This is the bug that keeps the verdict at **NOT READY**.

### Repro

I created a run whose verification command depends on a relative path inside the original workspace:
- build target: `subdir/unique-artifact.txt`
- verification command: `test -f subdir/unique-artifact.txt && echo FOUND_ARTIFACT`

First run: artifact absent, so the run fails.
Then I created the artifact **in the original workspace** and resumed the run.
A correct resume implementation should now pass.
It did not.

Observed output:

```json
{
  "first_run_summary": {
    "run_id": "run-ed0e12b842d9",
    "terminal_status": "failed",
    "completed_tasks": [],
    "failed_tasks": [
      "workspace-task"
    ],
    "partial_tasks": [],
    "blocked_reason": "criterion c1 failed: command exited 1: ",
    "integration_status": null,
    "total_runtime_seconds": 0.0040051937103271484,
    "cost_summary": {
      "backends_used": [
        "local-shell"
      ],
      "total_wall_clock_seconds": 0.004006147384643555,
      "retries_total": 0,
      "subagents_spawned": 1,
      "estimated_tokens": null,
      "notes": ""
    }
  },
  "artifact_created_after_first_run": "/var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r3-workspace-0wahgo69/subdir/unique-artifact.txt",
  "resume_exit": 3,
  "resume_stdout": "resumed run run-ed0e12b842d9\nreconciled 0 in-flight attempts\nterminal_status: failed",
  "resume_stderr": "",
  "final_result": {
    "run_id": "run-ed0e12b842d9",
    "terminal_status": "failed",
    "completed_tasks": [],
    "failed_tasks": [
      "workspace-task"
    ],
    "partial_tasks": [],
    "blocked_reason": "criterion c1 failed: command exited 1: ",
    "integration_status": null,
    "total_runtime_seconds": 0.0037949085235595703,
    "cost_summary": {
      "backends_used": [
        "local-shell"
      ],
      "total_wall_clock_seconds": 0.0037958621978759766,
      "retries_total": 0,
      "subagents_spawned": 1,
      "estimated_tokens": null,
      "notes": ""
    }
  }
}
```

### Root cause

`workspace_root` is used on the initial `run` path:
- `cmd_run()` reads `--workspace-root` / `CRUCIBLE_WORKSPACE_ROOT` and passes it into `execute_run()` (`src/crucible/runtime/cli.py:171-183`)

But `cmd_resume()` does **not**:
- it reloads the plan + manifest
- then calls `execute_run()` with **no `workspace_root` at all** (`src/crucible/runtime/cli.py:323-328`)

So `execute_run()` falls back to `os.getcwd()` (`src/crucible/runtime/run_executor.py:62-68`).

Worse: the manifest does not persist `workspace_root`, so resume has nothing authoritative to restore (`src/crucible/runtime/run_store.py:37-51`).

### Why this is a blocker

Because it breaks the main production claim of a durable run runtime:
- a long-running run can be interrupted
- the artifact can be fixed in the correct workspace
- `resume` can still fail forever because it replays verification in the wrong directory

This is exactly the class of bug that shows up under real OpenClaw usage: runs happen in detached/background/restarted contexts. If cwd is ambient, the runtime is not trustworthy.

### Likely blast radius

This is not isolated to explicit `resume`.
The detached CLI path also shells out into `resume` (`src/crucible/runtime/cli.py:141-150`), so direct CLI `run --detach --workspace-root ...` is very likely subject to the same bug unless the environment happens to carry the right cwd.

---

## Round-3 scorecard

- Semantic bypass exact case: **fixed**
- Bridge-backed executor path: **fixed**
- OpenClaw tool structured contract: **fixed**
- `watch --follow` blocking/streaming: **fixed**
- Incremental `resume`: **fixed**
- New blocker introduced/exposed: **yes**
  - `resume`/durability path does not preserve workspace contract

---

## Final recommendation

**NOT READY**.

This is much closer than Round 2. The six specific issues I asked to be fixed are fixed.

But I would still block production rollout until the workspace bug is closed, because it undercuts exactly the part of the system that needs to be most reliable under OpenClaw: interruption + resume.

### Required before signoff

1. **Persist `workspace_root` in the run manifest**
   - make it part of authoritative run state

2. **Use that persisted workspace on `resume`**
   - do not fall back to ambient cwd for a known run

3. **Add an adversarial regression test**
   - initial run fails in workspace A
   - artifact is created in workspace A
   - `resume` from cwd B succeeds because it restores workspace A

4. **Also test detached CLI runs with `--workspace-root`**
   - because detached goes through `resume`

If you fix that one blocker, I would re-run and expect this to move to **READY WITH CONDITIONS** or full **READY** depending on the detach-path result.
