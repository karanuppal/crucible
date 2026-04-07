# Verdict: NOT READY

Round 2 fixed two of the three round-1 blockers, but it did **not** make Crucible production-ready for OpenClaw.

What got fixed is real:
- `crucible.runtime.openclaw_tool` now imports
- the executor now runs real verification commands instead of fabricating passing evidence

What is still not production-ready:
- the new OpenClaw bridge is **not actually integrated into the executor path** the repo tells embedders to use
- the OpenClaw tool wrapper is still **machine-interface broken** (no structured `run_id`, broken `status`, dropped `embedding_session_ref`)
- the harness is still **easy to fool with semantically empty verification commands** like `echo PASS_OK`
- `watch` still does not stream, and `resume` reruns already-completed work

If you ship this into OpenClaw tomorrow, you are still shipping a verifier prototype plus a misleading tool boundary — not a trustworthy chat-native software build harness.

---

## Round 1 blocker re-verification

### 1. `openclaw_tool.py` import failure

**Round 1:** blocker. Syntax error on import.

**Round 2 result:** fixed.

Observed command:

```bash
$ cd /Users/millieclaw/Projects/crucible
$ uv run python -c 'import crucible.runtime.openclaw_tool'
```

Observed output:

```text
(stdout empty)
(stderr empty)
exit: 0
```

Verdict: **fixed**.

---

### 2. Validation theater / fabricated passing evidence

**Round 1:** blocker. The harness would mark obviously impossible verification as `complete`.

**Round 2 result:** the new executor really does run shell commands. For the two killer cases that reach runtime normally, it now fails honestly.

#### Case A — nonexistent command

Observed run:

```text
=== nonexistent ===
exit_code: 3
stdout:
run_id: run-c5ef26985f5b
run_root: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r2-ay0lgcq3/runs/run-c5ef26985f5b
terminal_status: failed
completed: []
failed: ['verify-task']
```

#### Case B — `false`

Observed run:

```text
=== false_cmd ===
exit_code: 3
stdout:
run_id: run-34b8b7e35707
run_root: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-r2-ay0lgcq3/runs/run-34b8b7e35707
terminal_status: failed
completed: []
failed: ['verify-task']
```

#### Case C — `echo BAR` with `expected_output: "FOO"`

This one exposed an important nuance.

**Exact CLI case requested in the validation plan does not reach runtime anymore.** It is rejected earlier by preflight because `expected_output` must be at least 4 chars.

Observed run:

```text
=== wrong_output ===
exit_code: 2
stderr:
plan failed preflight validation:
  ERROR [EXPECTED_OUTPUT_TOO_SHORT]verify-task.c1 task verify-task criterion c1 expected_output must be ≥4 chars
```

So:
- the exact review prompt expectation of “exit 3 + terminal_status: failed” is **not literally true** for `FOO`
- the reason is not validation theater; it is **preflight gating**
- if I force the exact case past preflight and run the executor directly, it fails honestly:

```json
{
  "run_id": "run-dcdb391cf2b4",
  "terminal_status": "failed",
  "blocked_reason": "criterion c1 failed: expected substring 'FOO' not found in stdout"
}
```

Verdict: **substantially fixed**, with a validation-plan mismatch on the exact `FOO` case.

---

### 3. OpenClaw bridge was a stub

**Round 1:** blocker. No real bridge code.

**Round 2 result:** partially fixed only.

There is now real code in `src/crucible/runtime/openclaw_bridge.py`:
- `SimulatedOpenClawBridge`
- `SessionsSpawnBridge`

That is better than round 1. But the claimed production path is still not closed.

I forced the current executor to use the bridge-backed adapter the way the code/comments imply embedders should:

```python
bridge = SessionsSpawnBridge(store, spawn_callable=fake_spawn, wait_callable=fake_wait)
summary = execute_run(..., adapter_factory=lambda s: [bridge.adapter])
```

Observed result:

```json
{
  "run_id": "run-d66f2d7f3c19",
  "terminal_status": "failed",
  "completed_tasks": [],
  "failed_tasks": ["t1"],
  "blocked_reason": "criterion c1 failed: no detail"
}
```

Persisted adapter state after that run:

```json
{
  "openclaw_session_id": "oc-t1.c1",
  "status": "running",
  "finished_at": null
}
```

Why this fails:
- `execute_run()` only knows the `BackendAdapter` interface
- it does `spawn()` and then immediately `collect()`
- `OpenClawSubagentAdapter.collect()` returns the persisted state as-is
- no code in `execute_run()` calls `SessionsSpawnBridge.run_spec_to_completion()`
- therefore the new bridge is **unit-tested in isolation but disconnected from the real execution path**

Verdict: **not fixed at the production path level**. The stub became a library, but not a working end-to-end OpenClaw runtime.

---

## Round 1 → Round 2 delta scorecard

| Item | Round 1 | Round 2 | Judgment |
|---|---|---|---|
| `openclaw_tool.py` importability | Syntax error, unusable | Imports cleanly | ✅ Fixed |
| Fabricated validation evidence | Could mark impossible commands `complete` | Real shell execution now used | ✅ Fixed at executor level |
| Exact `echo BAR` / `FOO` adversarial case | Passed incorrectly | Rejected at preflight (`exit 2`), forced runtime fails honestly | ⚠️ Fixed behavior, but validation-plan expectation is inaccurate |
| OpenClaw bridge existence | Missing/stub | Real bridge module added | ⚠️ Improved |
| OpenClaw bridge usability | No path | Still not integrated with `execute_run()` | ❌ Still a blocker |
| `watch` semantics | Replay only | Replay only | ❌ Not fixed |
| `resume` semantics | Fake note only | Executes, but reruns completed work and is not truly incremental | ⚠️ Better, still unsafe |
| Tool wrapper machine-readability | Broken import | Imports, but still not a reliable OpenClaw tool contract | ❌ Still broken |

---

## New findings

These are the next-layer issues round 1 either did not hit or that the rework introduced/exposed.

### 1. The harness is still easy to fool with semantically empty verification commands

The new executor honestly runs the command it is given. Good.

But nothing enforces that the command actually validates the claimed artifact.

I ran this plan:
- `build_target: src/does_not_exist.py`
- `verification_command: echo PASS_OK`
- `expected_output: PASS_OK`

Observed result:

```text
EXIT 0
STDOUT
run_id: run-20143409355d
run_root: /var/folders/6v/x_mfxysn6cxcxkcx_b37ndv00000gn/T/crucible-semantic-bypass-jshgbgrp/runs/run-20143409355d
terminal_status: complete
completed: ['t1']
failed: []
```

And `result.json` recorded:

```json
{
  "terminal_status": "complete",
  "completed_tasks": ["t1"]
}
```

The target file never existed. The harness still said `complete`.

This is no longer “fabricated evidence by the orchestrator.” It is now **plan-level validation theater**: if the plan lies, Crucible accepts the lie as long as the shell command exits 0 and prints the expected string.

**Why this matters:** OpenClaw plans are LLM-authored. You cannot assume they are disciplined enough to make verification commands meaningful.

Severity: **BLOCKER** for any claim of “validated build harness.”

---

### 2. `SessionsSpawnBridge` exists, but the executor cannot actually use it

This is the most important new blocker.

The repo now tells embedders to use `SessionsSpawnBridge`, and `cli.py` even says embedders can override `execute_run()` with an adapter factory “e.g. one backed by SessionsSpawnBridge.”

That is false as written.

Why:
- `SessionsSpawnBridge` is **not** a `BackendAdapter`
- `execute_run()` only consumes `BackendAdapter`s
- the only adapter exposed by the bridge is `bridge.adapter`, which is `OpenClawSubagentAdapter`
- `execute_run()` immediately calls `collect()` after `spawn()` and never waits
- result: OpenClaw-backed runs fail with adapter status still `running`

This is not just a documentation gap. It means the bridge cannot power the main runtime without more integration code.

Severity: **BLOCKER**.

---

### 3. The OpenClaw tool wrapper is still not a reliable tool contract

The syntax error is fixed, but the wrapper is still not production-ready.

I invoked `crucible.runtime.openclaw_tool.execute()` directly for a successful run.

Observed tool result:

```json
{
  "raw": "failed: []",
  "exit_code": 0,
  "status": "ok"
}
```

That is already wrong in three ways:
- no `run_id`
- no `run_root`
- the only parsed `raw` field is the **last human-readable line** of stdout (`failed: []`), which is meaningless as a machine contract

I then called `status` through the same wrapper.

Observed result:

```json
{
  "raw": "failed: []",
  "exit_code": 0,
  "status": "ok"
}
```

So `status` is effectively broken too.

I also checked whether `embedding_session_ref` survives into the manifest.

Observed manifest:

```json
{
  "embedding_surface": "openclaw",
  "embedding_session_ref": ""
}
```

So the wrapper accepts `embedding_session_ref` but drops it.

Root causes:
- `openclaw_tool.py` does not force `--json` / `--jsonl` for `run`, `status`, or `resume`
- it tries to parse human-readable CLI output as if it were structured
- it overwrites `raw` line-by-line and ends up keeping only the last line
- it never threads `embedding_session_ref` into the CLI

Severity: **BLOCKER**.

---

### 4. `watch` still does not stream events as they happen

I ran a detached job whose verification command sleeps for 2 seconds:
- `verification_command: sleep 2; echo PASS_OK`

Then I immediately called `watch`.

Observed behavior:

```text
WATCH_SECONDS 0.042
WATCH_EXIT 0
WATCH_STDOUT
{"type":"run_started", ...}
{"type":"run_resumed", ...}
{"type":"orchestrator_started", ...}
{"type":"tasks_loaded", ...}
{"type":"task_dispatched", ...}
{"type":"criterion_dispatched", ...}
```

Then 2.5 seconds later:

```text
STATUS_AFTER_WAIT
run_id: run-58f5b49bbafa
phase: done
status: complete
events: 9
attempts: 1
terminal_status: complete
```

So `watch` returned immediately with the events that already existed, then exited before the terminal events were written. That is not streaming.

The existing test `test_watch_streams_events` only asserts “got at least one event.” That is why this escaped.

Severity: **HIGH**.

---

### 5. `resume` reruns already-completed work

Round 1 found `resume` was fake. Round 2 made it execute, which is progress.

But it still does not resume intelligently.

I created a run with an already-complete attempt on disk, then resumed it using a verification command that increments a counter file as a side effect.

Observed result:

```text
EXIT 0
STDOUT
resumed run run-c45f13ca3b43
reconciled 0 in-flight attempts
terminal_status: complete

COUNT 2
```

The counter started at `1`. After resume it became `2`.

Meaning:
- resume did **not** skip the already-completed attempt
- it simply re-executed the task plan from scratch

That is bad even for verification-only semantics, and it becomes dangerous if anyone tries to use this path for side-effectful work.

Severity: **HIGH**.

---

### 6. No workspace / repo contract in the OpenClaw path

The runtime executes verification commands in `os.getcwd()`.
- `execute_run()` hardcodes `cwd=os.getcwd()` in the `AdapterRunSpec`
- `openclaw_tool._run_cli()` does not set `cwd`
- the tool interface has no `workspace`, `repo_root`, or `worktree_path`

So in a real OpenClaw deployment, the verification command runs in whatever directory the gateway process happens to be in.

That is a major end-to-end hole for real builds.

Severity: **HIGH**.

---

## OpenClaw bridge gap analysis (round 2)

### Is there now real code?

Yes. This is no longer a pure stub. `openclaw_bridge.py` is real code.

### Does it close the production gap?

No.

### What an embedder actually has to do today

To use `SessionsSpawnBridge`, the embedder must still figure out all of this themselves:

1. how to convert a Crucible criterion into a real OpenClaw `sessions_spawn` call
2. how to block until terminal state in `wait_callable`
3. how to translate OpenClaw completion details into the dict shape the bridge expects
4. how to choose a working cwd/workspace for the run
5. how to make that path cooperate with `execute_run()` at all, since `execute_run()` does not call `run_spec_to_completion()`

That last point is the killer. Even if the embedder supplies a perfect `sessions_spawn` wrapper, the provided executor path still does not use it correctly.

### Is the contract clear?

Partly, but not enough.

What is clear:
- spawn callable signature
- wait callable signature
- expected return payload shape

What is unclear / missing:
- how this plugs into `execute_run()` without custom glue
- whether the bridge is intended to be synchronous, event-driven, or both
- how restart recovery is supposed to reattach to an already-running OpenClaw session
- what the canonical workspace/repo semantics are
- how artifact paths are supposed to line up with later verification

### Bottom line

Round 1’s “bridge is missing” blocker has become:

> “bridge code exists, but the repo still does not ship a working OpenClaw execution path.”

That is better than round 1, but still **not ready**.

---

## Test pack honesty check

### What is genuinely better

I ran the claimed rework test pack plus the full suite:

```text
52 targeted runtime/adversarial tests passed
479 total tests passed
```

That part is real.

### What the new tests actually prove

They prove these narrow claims well:
- runtime modules import
- `LocalShellAdapter` runs real commands honestly
- direct shell-command failure modes (`false`, nonexistent command, wrong output with long-enough expected string) now fail
- the standalone bridge classes behave as unit-tested wrappers
- `--detach` now starts a background process
- `resume` now executes something rather than just logging a note

### What they do **not** prove

#### A. They do not prove the OpenClaw path works end-to-end

`test_openclaw_bridge.py` only unit-tests the bridge object itself.

It does **not** test:
- `execute_run()` with the bridge-backed path
- the CLI using the bridge
- the tool wrapper using the bridge
- a real fake-host `sessions_spawn` → wait → executor lifecycle

And as shown above, the obvious integration path fails.

#### B. They do not prove `watch` streams

`test_watch_streams_events` only checks that `watch` outputs at least one event. Replay passes that test.

#### C. They do not prove `resume` is incremental or safe

The new tests prove `resume` re-executes. They do **not** prove it skips already-complete work. In fact, it doesn’t.

#### D. They do not cover the still-trivial semantic bypass

The adversarial plan explicitly called for a “lying verification” case:
- command exits 0
- produces no real evidence

That gap is still there. The harness still returns `complete` for `echo PASS_OK` against a nonexistent target.

#### E. They do not cover `openclaw_tool.py` behavior beyond import

There is an import test. Good.

There is still no test proving the wrapper returns:
- `run_id`
- structured status
- manifest/session metadata
- correct parsing for run/status/resume

That is why the wrapper can be importable and still unusable.

### Test-pack verdict

The test rework is **real and materially better**.

But it overstates what has been validated. The new tests mostly certify:
- honest local shell verification
- isolated bridge unit behavior
- superficial CLI lifecycle behavior

They do **not** certify a production OpenClaw integration.

---

## End-to-end walkthrough: “Build me a JWT auth system with tests.”

Here is what actually happens today.

### Step 1: OpenClaw decides to use Crucible

The skill is selected. It tells the model to produce a plan with tasks and verification triples.

So far, okay.

### Step 2: The model drafts a plan

This is still largely promptcraft. Crucible itself is not generating the plan.

Best case:
- the model writes disciplined criteria like `pytest tests/test_auth_service.py -v`

Failure case:
- the model writes lazy criteria like `echo PASS_OK`
- Crucible will accept them if they are non-generic and long enough

### Step 3: OpenClaw calls the `crucible` tool

This is where the current production story already breaks.

The wrapper returns human-output garbage as machine output.

Observed successful `run` result via `openclaw_tool.execute()`:

```json
{
  "raw": "failed: []",
  "exit_code": 0,
  "status": "ok"
}
```

So OpenClaw does **not** get a reliable `run_id` back.

Without a `run_id`, the advertised follow-up workflow (`status`, `watch`, `resume`) is already compromised.

### Step 4: Suppose OpenClaw somehow recovers the run_id anyway

Now there are two realistic paths.

#### Path A — use the default CLI/runtime path

This path does **not build anything**.

It only runs verification commands locally via `LocalShellAdapter`.

So if the code does not already exist on disk in the current working directory:
- honest verification commands fail
- no JWT auth system gets built

If the plan cheats with `echo PASS_OK`:
- the run completes even though nothing was built

So default path is either:
- honest failure, or
- meaningless success

#### Path B — try to use the new OpenClaw bridge for a real build path

The docs/comments imply embedders can back `execute_run()` with `SessionsSpawnBridge`.

In practice, this fails because the executor only calls `spawn()` and `collect()` on a `BackendAdapter`. It never invokes the bridge’s wait path.

So the sub-agent session gets spawned, but the executor records the criterion as failed while the adapter state is still `running`.

Meaning:
- the supposedly “production” OpenClaw path still does not actually run end-to-end

### Step 5: User asks for progress

`watch` is supposed to stream.

It does not. It replays existing events and exits.

So for a real long-running job the monitoring story is still weak and misleading.

### Step 6: Gateway restarts or user comes back later

`resume` now does execute. Good.

But it does not do true continuation logic. It replays the full plan and can rerun already-completed work.

So the durability story is still overstated.

### End-to-end verdict

For the user-facing scenario “build me a JWT auth system with tests,” the current real outcomes are:

1. **tool wrapper gives OpenClaw bad structured output**
2. **default path does not build anything**
3. **bridge path is not integrated into the executor**
4. **monitoring is still fake-streaming**
5. **resume is blunt re-execution, not true recovery**
6. **weak plans can still produce meaningless green runs**

That is not shippable.

---

## Top 5 risks for shipping tomorrow

### 1. OpenClaw bridge exists on paper but not in the real executor path
- **Severity:** BLOCKER
- **Why it matters:** the repo now claims a production bridge, but `execute_run()` cannot actually use it correctly.
- **Recommendation:** fix now

### 2. `openclaw_tool.py` still does not provide a trustworthy machine contract
- **Severity:** BLOCKER
- **Why it matters:** OpenClaw needs structured `run_id`, `status`, and monitoring hooks. The wrapper currently returns mangled human output and drops `embedding_session_ref`.
- **Recommendation:** fix now

### 3. Semantic verification bypass still allows meaningless green runs
- **Severity:** BLOCKER
- **Why it matters:** `echo PASS_OK` against a nonexistent build target still yields `terminal_status: complete`. For LLM-authored plans, this is fatal.
- **Recommendation:** fix now

### 4. `watch` and `resume` still over-promise durability
- **Severity:** HIGH
- **Why it matters:** `watch` is replay-only; `resume` reruns completed work. Real long-running OpenClaw UX will be confusing and can repeat side effects.
- **Recommendation:** fix now if durability is a launch claim; otherwise strip the claim

### 5. No workspace/repo contract means commands run in the wrong place by default
- **Severity:** HIGH
- **Why it matters:** verification runs in process cwd, not an explicit project root. That is a serious production integration gap.
- **Recommendation:** fix now

---

## Concrete numbered action items by severity

### BLOCKER

1. **Integrate the bridge into the real executor path.**
   - Either make `execute_run()` bridge-aware, or provide a real OpenClaw-backed adapter whose `spawn()/collect()` semantics include waiting for terminal state.
   - Add an e2e test that runs `execute_run()` or CLI with a fake `sessions_spawn` host and proves the bridge path completes.

2. **Fix `openclaw_tool.py` to be structured-first, not stdout-scrape-first.**
   - Force `--jsonl` for `run`/`watch`
   - Force `--json` for `status`
   - Return `run_id`, `run_root`, and terminal summary deterministically
   - Preserve `embedding_session_ref`
   - Add dedicated wrapper tests beyond importability

3. **Close the semantic verification loophole.**
   - At minimum, require verification commands to reference or materially inspect the declared target/test artifact
   - Better: add a stronger verifier contract than arbitrary shell + substring
   - Add the missing adversarial test: nonexistent build target + `echo PASS_OK` must not yield `complete`

### HIGH

4. **Make `watch` actually tail new events until terminal or timeout.**
   - Current behavior is snapshot replay, not streaming
   - Add a test that starts a delayed run and asserts terminal events arrive without re-invoking `watch`

5. **Make `resume` incremental and skip already-complete attempts.**
   - Read attempt state
   - Avoid rerunning winning attempts
   - Add a test proving resume does not rerun completed work

6. **Add an explicit workspace/repo root contract.**
   - CLI + tool + manifest should all know where commands run
   - Stop relying on ambient `os.getcwd()`

7. **Update the signoff docs and validation matrix to match reality.**
   - G4 is not truly satisfied end-to-end
   - G5/G6 do not yet prove streaming watch or semantic anti-bypass behavior

### MEDIUM

8. **Resolve the `FOO` adversarial-case mismatch between validation plan and actual preflight rules.**
   - Either loosen preflight for this test shape, or update the docs to use a 4+ char expected string consistently

9. **Clarify the bridge contract in code and docs.**
   - Is the production story synchronous wait, event callback, or both?
   - How should restart recovery reattach?

10. **Decide what Crucible’s public promise is.**
   - If it is now “verification harness” rather than “build harness,” say that everywhere clearly
   - If it is meant to stay a build+verify harness, ship the missing build-path integration before launch

---

## Final recommendation

**NOT READY.**

Round 2 is a meaningful improvement over round 1. The repo is no longer dead on import, and the core shell-verification path is now honest about obvious command failures.

But the project is still not ready for OpenClaw production because the hardest production-facing problems remain unsolved:
- the OpenClaw bridge is not actually integrated into the executor path
- the OpenClaw tool wrapper is still not a usable machine interface
- weak LLM-authored plans can still generate meaningless green runs
- `watch` and `resume` still overstate durability semantics
- workspace/repo execution context is undefined

The honest status is:

> **Crucible is now a better verification prototype, but still not a production-ready OpenClaw software-build harness.**

If you want a credible next signoff target, it should require:
1. one real OpenClaw-backed end-to-end execution path
2. a structured tool wrapper that returns usable run metadata
3. a semantic anti-bypass check for verification commands
4. true streaming `watch`
5. incremental `resume` that does not rerun completed work
