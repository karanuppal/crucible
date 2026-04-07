# Verdict: NOT READY

Crucible is **not** ready to be used by OpenClaw as a real production tool.

The blockers are not cosmetic. The OpenClaw tool wrapper does not even import, the OpenClaw event bridge is missing, runtime durability is mostly paper-only, and the validation path can mark obviously impossible tasks as `complete` because the orchestrator fabricates passing evidence instead of executing verification commands.

If you ship this tomorrow, you are not shipping a reliable software-build harness. You are shipping a convincing demo shell around an in-memory happy path.

---

## Executive summary

What is solid:
- The **preflight validator** is good. It meaningfully rejects bad task plans.
- The **run-store primitive** is a decent filesystem packet format for one run.
- A lot of the Phase 1–7 library substrate exists and is reasonably organized.

What is not solid:
- `src/crucible/runtime/openclaw_tool.py` has a **syntax error** and cannot be imported.
- The claimed OpenClaw production path depends on a **missing host bridge** that is not implemented or contract-tested.
- `Orchestrator._build_criterion_results()` **fakes validation evidence** instead of running the requested verification commands.
- `--detach`, `resume`, and `watch` do **not** provide real long-running runtime semantics.
- The runtime surface claims durability, fan-out/fan-in, and resumability that the actual execution path does not deliver.

I ran direct checks confirming the most important failures:
- `uv run python -c 'import crucible.runtime.openclaw_tool'` → **SyntaxError**.
- A detached run stays in `current_phase: intake`, `current_status: running`, with no attempts; `resume` only appends a note telling the embedder to re-invoke orchestration.
- A foreground run with a verification command that can never pass still ends as `terminal_status: complete`.

---

## Goal alignment scorecard by phase

| Phase | Score | Status | Reality |
|---|---:|---|---|
| Phase 1 — deterministic substrate | 7/10 | Mostly built | State contracts, ledger, and failure taxonomy exist. Good foundation. Not the problem. |
| Phase 2 — sub-agent management cluster | 4/10 | Partial | Core abstractions exist, but the real OpenClaw spawn/monitor/kill lifecycle is not actually delivered end-to-end. |
| Phase 3 — validation/review foundation | 3/10 | Under-delivered | The validator library is decent, but the runtime integration is not trustworthy because the orchestrator fabricates passing evidence. |
| Phase 4 — scheduling and memory foundation | 4/10 | Partial | Components exist, but scheduler/memory are barely driving runtime behavior. Mostly post-hoc bookkeeping. |
| Phase 5 — unified project workflows | 6/10 | Mostly library-complete | Intake/greenfield utilities exist and look plausible, but they are not what makes Phase 8 production-ready. |
| Phase 6 — optional accelerators | 5/10 | Partial | Router/adapters exist, but the real OpenClaw backend path is half-embedded and not proven. Retry semantics are far below spec. |
| Phase 7 — orchestrator + integration glue | 4/10 | Partial | There is a working serial orchestrator skeleton, but it does not deliver trustworthy validation or real integration discipline. |
| Phase 8 — production runtime surface | 2/10 | Not shippable | CLI exists, run packet exists, but the actual production contract is broken: tool wrapper broken, resume fake, watch not live, bridge absent. |

### Bottom line on goal alignment

Crucible as implemented is **closer to “validated execution substrate with a thin demo runtime” than to “chat-native delegation harness OpenClaw can trust as a real build tool.”**

Major spec promises that are still missing, hand-waved, or under-implemented:
- **Natural-language decomposition discipline is externalized.** Crucible runtime expects a hand-authored task plan. It does not itself turn a user request into disciplined tasks.
- **Ambiguity gate is not truly front-door for the real user request.** It gates either externally-supplied findings or already-drafted task JSON.
- **Fan-out/fan-in is weak in the production path.** The orchestrator effectively runs serially and integration uses placeholder branch/worktree data.
- **Validation ladder is compromised at the runtime boundary.** Verification commands are not actually executed in the main run path.
- **Scheduling exists more as a component than as a behavior.** Concurrency/resource-aware execution is not what the runtime is doing.
- **Memory store exists, but retrieval/injection are not meaningfully shaping execution.**
- **OpenClaw embedding contract is incomplete and unproven.**
- **Durable run store is decent as a format, but not populated in a way that makes restart/recovery trustworthy.**

---

## Phase 8 component-by-component evaluation

### 1. `src/crucible/runtime/cli.py`

### What is good
- `lint-plan`, `run`, `status`, `watch`, `resume` are at least exposed as a coherent CLI surface.
- Exit code handling is broadly sensible.
- Foreground `run` with the default in-memory adapter works for a happy-path demo.

### What is bad
- `--detach` does not detach execution. It just creates a run packet and exits with: **“orchestrator invocation deferred to embedder.”** That is not a detached runtime. That is a stub.
- `resume` does not resume execution. It only calls `reconcile_in_flight_attempts()`, appends `run_resumed`, and prints: **“embedder must re-invoke Orchestrator.run_build with this run_id.”**
- `watch` is not a live stream. It simply replays the current contents of `events.jsonl` and exits.
- `cmd_run()` accepts `--embedding` but **drops `embedding_session_ref` entirely**. The run manifest supports it, but the CLI never passes it.
- The default CLI path is still demo-centric: foreground runs use `InMemoryAdapter`, which produces fake artifacts without doing real work.

### Verdict
Useful as a local debug/demo CLI. **Not a production runtime surface.**

---

### 2. `src/crucible/runtime/run_store.py`

### What is good
- The run packet layout is reasonable: `run.json`, `tasks.json`, `events.jsonl`, `result.json`, `attempts/`, `adapter-state/`, `artifacts/`.
- Atomic temp-file writes are used in the right places.
- The API is clean enough to support durable run inspection.

### What is bad
- The implementation is **better than the way the runtime uses it**.
- Reconciliation of in-flight attempts is mostly theoretical because the runtime does **not** persist attempt records before work completes/fails.
- Important spec-level fields are not meaningfully populated by the actual execution path:
  - artifact manifests are mostly empty
  - per-attempt metadata is thin
  - integration details are not recorded
  - no real cost accounting
- It gives the appearance of restart-safe execution, but the runtime bridge does not write enough state at the right times for that promise to hold.

### Verdict
A decent durable packet format. **Not enough by itself to claim resumable execution.**

---

### 3. `src/crucible/runtime/preflight.py`

### What is good
- This is the strongest new Phase 8 component.
- It rejects empty plans, vague descriptions, generic targets, weak expected outputs, duplicate IDs, duplicate verification tuples, and malformed triples.
- It normalizes plans and gives structured findings.
- It materially improves decomposition discipline compared with accepting arbitrary task JSON.

### What is missing / weak
- It only validates the plan it is handed. It does not solve the upstream problem of generating a good plan from the user’s request.
- `retryable` is normalized but effectively unused downstream.

### Verdict
**Real value. Ship-worthy as a lint layer.** Not enough to make the overall runtime trustworthy.

---

### 4. `src/crucible/runtime/openclaw_adapter.py`

### What is good
- Sensible idea: wrap OpenClaw sub-agent sessions as a `BackendAdapter` with persisted adapter state.
- `poll()` and `collect()` reading persisted state is the right shape for post-restart continuity.
- Event ingestion is idempotent enough for repeated terminal updates.

### What is bad
- The actual bridge is missing. This adapter is only a shell around an injected `spawn_fn`.
- The contract is incomplete: `ingest_event()` requires a **`handle_id`**, but the host bridge naturally knows the **OpenClaw session id**. The adapter stores the mapping internally, but `spawn_fn` is never given `handle_id`, so the host has no clean contract for routing events back by handle.
- `kill()` is not real cancellation. It mostly marks local state.
- No timeout/heartbeat watchdog exists for stale OpenClaw runs.
- `collect()` returns `AdapterRunResult` without backend session metadata, even though the productionization review explicitly said that metadata should be carried.

### Verdict
Promising shape, **not a finished adapter contract**.

---

### 5. `src/crucible/runtime/run_executor.py`

### What is good
- It is a reasonable place for CLI/runtime glue.
- It converts plans to `TaskDefinition`s, builds adapters, constructs a router/orchestrator, and writes a final summary.

### What is bad
- It writes `task_dispatched` events **before** real backend dispatch is durably represented.
- It writes `TaskAttemptRecord`s only **after** the task is already completed or failed. That breaks the claimed restart/reconciliation story.
- It assumes `adapters[0]` is the backend for all attempts, which is wrong if router fallback happens.
- It does not persist real per-attempt workspace refs, artifact refs, or backend run/session IDs.
- It does not wire router failover state into the run packet in a meaningful way.
- It does not expose live progress or partial state beyond final summaries.
- It does not support actual resume.

### Verdict
Acceptable bridge for a demo. **Too lossy for production durability claims.**

---

### 6. `src/crucible/runtime/plan_loader.py`

### What is good
- Straightforward mapping from normalized plan JSON to `TaskDefinition`.

### What is bad
- It is very thin and drops meaningful runtime semantics. In particular, `retryable` survives preflight normalization but is not preserved into execution behavior.
- There is no support for dependency structure or richer planning metadata.

### Verdict
Fine as a serializer. **Not enough for the richer runtime behavior the spec promises.**

---

### 7. `src/crucible/runtime/openclaw_tool.py`

### What is good
- In theory, this is the right boundary: expose Crucible as an OpenClaw tool and shell out to the CLI.

### What is bad
- **Blocker:** the file does not import. There is a syntax error at the end:
  - `return {"status": "error", "exit_code": 1, f"unknown mode: {mode}"}`
- Because of that, the actual OpenClaw tool surface is dead on arrival.
- Even after fixing syntax, the wrapper is still wrong:
  - It parses JSONL-ish events, but for `run`, `status`, and `resume` it does **not** force `--json`/`--jsonl`, so parsing is inconsistent.
  - It ignores `embedding_session_ref`.
  - It assumes `CRUCIBLE_CLI_PATH` is a single executable path, not a command with args.

### Verdict
**Current state: unusable.** This alone is enough for a NOT READY verdict.

---

### 8. `skills/openclaw/SKILL.md`

### What is good
- It gives the LLM a concrete schema and example plans.
- The plan templates are better than nothing.

### What is bad
- It oversells the runtime. The skill says runs survive restarts, `watch` gives incremental events, `resume` continues execution, and stuck sub-agents will eventually time out. That is not what the implementation currently guarantees.
- It quietly relies on the LLM to do the real decomposition work. That is operationally brittle and is not the same thing as Crucible embodying decomposition discipline itself.
- It treats the tool as production-ready when the actual wrapper is broken.

### Verdict
Useful draft guidance. **Not honest documentation for the current state of the system.**

---

### 9. `docs/validation/phase-8/`

### What is good
- The phase docs are organized and they clearly tried to think through production concerns.

### What is bad
- The signoff is too optimistic.
- The validation matrix claims coverage that does not match reality.
  - `test_resume_nonterminal_run` does not actually create a nonterminal run.
  - `watch` is described as streaming, but the implementation just replays current events and exits.
  - The OpenClaw event bridge is called a non-blocking open item when it is actually central to whether the real backend path works at all.
- The productionization review itself identifies future improvements that are, in practice, current blockers.

### Verdict
The docs read like a ship memo for a system that is still at the “runtime prototype” stage.

---

## OpenClaw embedding gap analysis

## Short answer
No, the current gap is **not acceptable** if the claim is “Crucible is ready to be used by OpenClaw as a real tool.”

## Why
Phase 8’s real backend story depends on code that does not exist in this repo:
- actually calling `sessions_spawn`
- tracking the mapping between Crucible `handle_id` and OpenClaw session id
- subscribing to OpenClaw completion/progress events
- routing those events into `OpenClawSubagentAdapter.ingest_event()`
- handling restart recovery of that bridge process

That is not a small plugin detail. That is the **entire production execution path**.

## The deeper problem
The contract is not just unimplemented. It is under-specified:
- The adapter wants `ingest_event(handle_id=...)`.
- The embedding host naturally receives events keyed by **session id**.
- `spawn_fn` returns the session id but is never handed the `handle_id` created inside the adapter.

So the bridge is not merely missing; the boundary between Crucible and OpenClaw is still awkward enough that the host has to reverse-engineer or out-of-band store the mapping.

## What Crucible should ship
At minimum, Crucible should ship a **reference bridge implementation** or a very small host-facing shim with contract tests. Specifically:
- a reference `spawn_fn` implementation showing how `sessions_spawn` is called
- a reference event router showing how OpenClaw progress/completion messages map to `ingest_event()`
- a clean mapping contract for `handle_id <-> session_id`
- restart/recovery behavior for that bridge
- one end-to-end integration test using a fake host that exercises the full bridge path

Without that, the phrase “owned by the embedding layer” is functioning as a place to hide the hardest production work.

## My judgment
- If the repo said **“Phase 8 provides the runtime packet + adapter shell; OpenClaw integration still pending”**, that would be fair.
- But for the actual question — *ready for OpenClaw as a real tool?* — the answer is **no**.

---

## Top 5 risks if you deploy this into OpenClaw production tomorrow

### 1. OpenClaw tool surface is dead on import
- **Severity:** BLOCKER
- **Why it bites:** `crucible.runtime.openclaw_tool` currently throws a `SyntaxError` on import. The tool cannot even register or execute.
- **Recommendation:** **Must fix pre-launch.** Add tests that import the module and exercise every mode.

### 2. “Validation passed” is not trustworthy
- **Severity:** BLOCKER
- **Why it bites:** The orchestrator can return `complete` for plans whose verification commands would obviously fail, because it synthesizes evidence instead of executing the checks.
- **Recommendation:** **Must fix pre-launch.** Replace synthetic criterion evidence with actual verifier execution or explicit builder/reviewer-emitted evidence that is independently checked.

### 3. Real OpenClaw backend path is missing and under-specified
- **Severity:** BLOCKER
- **Why it bites:** The production path depends on a non-existent bridge for spawn/event ingestion. Even if someone wires it quickly, the `handle_id`/session-id contract is clumsy and unproven.
- **Recommendation:** **Must fix pre-launch.** Ship a reference bridge/shim and one contract-tested end-to-end path.

### 4. Durability/resume claims will fail under real interruption
- **Severity:** HIGH
- **Why it bites:** Detached runs do not execute, `resume` does not continue execution, `watch` is not live, and in-flight attempts are not durably recorded before completion. A gateway restart will leave users with a run packet that looks recoverable but is not actually resumable.
- **Recommendation:** **Must fix pre-launch** if you intend to advertise durability. If you want to ship earlier, strip the durability claims and call it foreground-only experimental.

### 5. Runtime behavior is far simpler than the spec promise
- **Severity:** HIGH
- **Why it bites:** No real dependency-aware task graph, no meaningful parallel fan-out, no execution retry tiers per spec, integration uses placeholder worktree/branch data, and memory/scheduler do not materially drive execution. Large multi-task builds will behave much worse than the product promise suggests.
- **Recommendation:** **Can be partially deferred only if you narrow scope hard.** If the launch claim is “single-host experimental serial executor for pre-baked task plans,” that is tolerable. If the launch claim is “real OpenClaw software-build harness,” it is not.

---

## Test coverage honest assessment

427 tests passing is real, but it is **not evidence that the right things are working**.

## What the tests do cover reasonably well
- Preflight linting rules.
- Run-store file primitives.
- Some ambiguity/memory/workflow library behavior.
- Happy-path adapter persistence behavior using injected mocks.

## What the tests do not cover well enough

### 1. The actual OpenClaw tool surface
There are **no direct tests** protecting `openclaw_tool.py`, which is why a syntax error made it to the branch.

That alone disqualifies the Phase 8 test story from being called production-grade.

### 2. Real verification behavior
The tests normalize the fake validation story instead of challenging it.

The orchestrator tests literally describe synthesized evidence as “real evidence.” The runtime tests never prove that a task only completes when the specified verification command actually passes.

### 3. Real interruption / resume
The runtime suite claims resume coverage, but `tests/runtime/test_e2e.py::test_resume_nonterminal_run` does **not** create a nonterminal run. It runs a normal foreground flow and then calls `resume` on what is already a finished run.

That is not a restart/resume test. It is a smoke test for the command not crashing.

### 4. Real watch semantics
`watch` is only tested as “it emits at least one event.” That is replay, not live streaming.

### 5. The real OpenClaw bridge path
No tests exercise:
- `sessions_spawn`
- event delivery keyed by OpenClaw session id
- restart of the embedding process
- mapping session completions back into adapter state

### 6. Failure modes in new Phase 8 glue
Not adequately tested:
- adapter factory failures through the tool surface
- malformed or missing CLI executable path
- tool wrapper mode parsing
- router failover state being reflected in run-store attempts
- detached execution that actually continues elsewhere
- partial completion with durable continuation

## Test-suite verdict
The test count is inflated by strong library coverage and weak happy-path runtime coverage.

The honest statement is:
- **The repo has a lot of tests.**
- **The production-critical Phase 8 behavior is not tested at a level that justifies shipping.**

---

## End-to-end usability walkthrough

Scenario: user says, **“build me a JWT auth system with tests.”** OpenClaw decides to use Crucible.

### What the ideal story claims
1. OpenClaw routes to Crucible.
2. Crucible decomposes the request into validated tasks.
3. It fans out sub-agents.
4. It validates outputs against explicit criteria.
5. It survives interruption.
6. The user can monitor progress and later resume.
7. The user gets a durable, auditable, validated result.

### What actually happens today

#### Step 1: OpenClaw selects the skill
- The skill can help the LLM draft a plan JSON.
- This part is mostly promptcraft plus templates. There is no deep runtime intelligence here.

#### Step 2: Plan linting
- If the drafted plan is too vague, preflight can reject it. Good.
- If the plan is structurally good, it passes.

#### Step 3: OpenClaw calls the Crucible tool
- **Current reality:** this likely fails immediately because `openclaw_tool.py` does not import.
- User-visible result: tool error / failure to invoke Crucible.

#### Step 4: Assume you hotfix the syntax error and try again
Two branches:

##### Branch A: you go through the CLI default path
- The default path uses `InMemoryAdapter`.
- No real coding agent is launched.
- The adapter returns a fake artifact path.
- The orchestrator fabricates evidence for the criteria.
- The run can end as `complete` without the JWT system existing and without tests having run.

User-visible result:
- Crucible reports a clean run.
- The result is not trustworthy.

##### Branch B: you wire in the real OpenClaw adapter manually
- The adapter calls your injected `spawn_fn`.
- Real sub-agent sessions may spawn.
- Now you need the missing bridge to route completion/progress back to `ingest_event()`.

If that bridge is not present:
- the router polls persisted adapter state
- state stays `running`
- eventually the task degrades into a non-complete result / failure path
- the run blocks or fails after waiting

User-visible result:
- long pause, weak status visibility, then a failure or confusing stuck run

If that bridge is present but minimally hacked together:
- tasks may eventually complete
- but validation still relies on synthetic criterion evidence unless you also rework the verifier path

User-visible result:
- progress might appear
- completion is still not strong proof that the requested tests actually passed

#### Step 5: User asks for status / watch
- `status` can show a snapshot of files on disk.
- `watch` replays existing events and exits. It is not a live monitor.

User-visible result:
- looks kind of okay for finished runs
- poor for active runs

#### Step 6: Gateway restarts mid-run
- Detached execution is not truly managed by Crucible.
- `resume` does not actually continue execution; it just flags state and tells the embedder to re-run orchestration.
- The runtime often lacks properly persisted in-flight attempts anyway.

User-visible result:
- false sense of durability
- manual/hacky recovery required

### Usability verdict
For a real OpenClaw user, today’s experience is either:
- **immediate tool failure**, or
- **a demo-grade run that looks more real than it is**, or
- **a half-wired backend path that stalls on the missing event bridge**.

That is not shippable.

---

## Concrete action items

1. **[BLOCKER] Fix `openclaw_tool.py` and add import/runtime tests.**
   - Remove the syntax error.
   - Add tests that import the module and call all modes.
   - Force structured CLI output (`--json` / `--jsonl`) consistently.
   - Thread `embedding_session_ref` through the CLI and manifest.

2. **[BLOCKER] Replace synthetic validation with real verification execution.**
   - The runtime must not mark a task complete unless the requested verification command actually passes or equivalent independently verifiable evidence exists.
   - Add adversarial tests where impossible verification commands must fail.

3. **[BLOCKER] Ship a reference OpenClaw bridge.**
   - Implement the host-side spawn + event-router shim.
   - Clean up the `handle_id <-> session_id` contract.
   - Add one end-to-end contract test using a fake host event stream.

4. **[BLOCKER] Make detach/resume real or stop claiming it.**
   - Persist in-flight attempts before dispatch.
   - Support actual continuation of nonterminal runs.
   - If this is not ready, remove the feature from skill/docs and mark it experimental.

5. **[HIGH] Make `watch` actually watch.**
   - Tail new events until terminal, or expose a proper polling/stream protocol.
   - Add tests proving live progression, not just replay.

6. **[HIGH] Record real per-attempt runtime data.**
   - backend/session id
   - start/finish timestamps
   - workspace/worktree refs
   - preserved artifacts
   - failover chain
   - partial outputs

7. **[HIGH] Implement the retry semantics promised in the spec or scale back the claim.**
   - spawn retry
   - execution retry for retryable failure classes
   - timeout retry honoring `retryable`

8. **[HIGH] Make integration honest.**
   - Stop passing placeholder `worktree_path=""` and synthetic branch names into fan-in.
   - Either wire real integration inputs or explicitly disable integration in the runtime surface.

9. **[MEDIUM] Decide what Crucible is responsible for upstream of runtime.**
   - If decomposition stays outside Crucible, document that honestly.
   - If Crucible is supposed to embody decomposition discipline, add a reference planner/decomposer layer or stricter plan-contract tooling.

10. **[MEDIUM] Rewrite the validation docs/signoff to match reality.**
    - Remove “ready to ship” language.
    - Reclassify the OpenClaw bridge as a blocker, not a deferred nice-to-have.
    - Correct the runtime coverage claims.

---

## Final recommendation

Do **not** ship Crucible into OpenClaw production tomorrow.

If you want a truthful status label, it is this:

> **Crucible has a promising library substrate and a useful plan preflight layer, but the Phase 8 “production runtime surface” is still a prototype.**

The minimum bar before real OpenClaw launch is:
- tool wrapper fixed and tested
- real OpenClaw bridge shipped and contract-tested
- validation made real
- detach/resume/watch either implemented properly or removed from the production claim

Until then, the right call is **NOT READY**.
