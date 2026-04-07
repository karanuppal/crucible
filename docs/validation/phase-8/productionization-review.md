# Productionization Review — Phase 8

**Verdict: APPROVED WITH CHANGES**

The proposed direction is broadly correct, but the current breakdown is **missing one critical layer**: a durable run-service boundary between Crucible's deterministic orchestrator and OpenClaw's push-based sub-agent runtime. If you ship only `crucible.cli` + `SubAgentAdapter` + `SKILL.md` + one smoke test, you will get a compelling demo but a brittle production system.

The right answer for v5.3 is:
- keep Crucible as a **library-first harness**,
- add a **CLI** as the operator and skill entry surface,
- add a **real OpenClaw-backed adapter**,
- but also add a **durable run record / event stream / resume model** so long-running chat-native execution can survive restarts, partial completion, and retries without semantic drift.

In other words: the proposal has the right bones, but it is underspecified where production systems usually fail — lifecycle durability, observability, progress streaming, retry semantics, and decomposition quality control.

---

## A. Architectural soundness

### A1. Is the CLI / SubAgentAdapter / Skill / Smoke-test breakdown the right shape?

**Yes, as a Phase 8 skeleton. No, as a productionization plan.**

The four proposed pieces are the correct top-level entry points:
- `crucible.cli` gives you a stable invocation surface
- `subagent_adapter` gives you a real execution backend
- `SKILL.md` gives OpenClaw auto-selection and workflow adoption
- a smoke test gives you an end-to-end reality check

But that is only enough for **activation**, not **productionization**.

A real productionization phase also needs:
- durable run IDs and persisted run state
- resumability and idempotent retry behavior
- progress/event emission as a first-class contract
- decomposition validation before execution starts
- an explicit mapping from push-based backend events to orchestrator state transitions
- observability artifacts for audit and debugging

Without those, you have a thin wrapper over a fundamentally synchronous in-process model.

### A2. Is the OpenClaw ↔ Crucible ↔ sub-agent split clean and durable?

**Conceptually yes. Operationally not yet.**

The intended split is correct:
- **OpenClaw** should own conversational interpretation, UX, and tool orchestration at the chat boundary
- **Crucible** should own deterministic lifecycle, validation, scheduling, memory, and integration semantics
- **Sub-agents** should own bounded task execution

That is a clean separation of responsibilities.

The leakage risk appears in two places:

#### Leakage 1: decomposition quality
If decomposition lives entirely in the OpenClaw skill body, Crucible becomes dependent on an LLM-generated structure it does not control. That means the most important upstream contract — task shape, criterion quality, verification specificity — is outside the harness boundary.

That is acceptable only if Crucible **fails closed** on bad decompositions.

#### Leakage 2: lifecycle semantics
Crucible's current adapter contract is synchronous and polling-oriented:
- `spawn`
- `poll`
- `collect`
- `kill`

OpenClaw sub-agents are message-driven and push-based. That means the current split is not yet durable because one side assumes **active polling** while the other assumes **event delivery**.

That mismatch is the main architectural gap in the proposal.

### A3. Should decomposition live in the LLM skill body or inside Crucible?

**Recommendation: hybrid model.**

Do **not** push full decomposition into Crucible first. That would overfit the library to one embedding surface and force you to build a prompt-engine inside Python before you have the runtime bridge stable.

Do **not** leave decomposition entirely in the skill forever either. That makes Crucible a passive executor of untrusted, low-discipline task plans.

The right split is:
- **OpenClaw skill** performs natural-language interpretation and first-pass decomposition
- **Crucible** performs strict structural validation, normalization, and rejection of weak task plans
- later, Crucible can optionally ship decomposition helpers/templates or even a planner module, but not as the Phase 8 dependency

Trade-offs:

#### Decomposition in the skill body
Pros:
- fastest path to usability
- uses the LLM in the environment where the user already is
- keeps Crucible engine-agnostic
- lets different chat surfaces produce different plans

Cons:
- quality varies by prompt and model
- hard to guarantee consistent criterion quality
- raises false confidence if bad plans pass through
- harder to replay deterministically if the original decomposition was not persisted

#### Decomposition in Crucible
Pros:
- centralized standards and normalization
- better auditability and deterministic replay
- easier to enforce cross-surface consistency

Cons:
- pushes language/planning complexity into the harness
- risks coupling Crucible to one planner implementation
- harder to maintain if multiple surfaces want different planning styles

**Bottom line:** Phase 8 should keep planning at the chat layer, but Crucible must add a **TaskDefinition intake validator** strong enough to reject vague plans.

---

## B. Missing pieces

### B1. What's missing from the proposal?

The proposal omits six production-critical concerns:

1. **Durable run model**
   - Every `crucible run` invocation needs a persisted `run_id`, run manifest, and event log.
   - If the host process or chat session dies, the run must be inspectable and resumable.

2. **Event streaming contract**
   - "Streams progress" is too vague.
   - You need a defined event schema: `run_started`, `task_dispatched`, `backend_selected`, `subagent_spawned`, `task_partial`, `task_validated`, `integration_started`, `run_blocked`, `run_completed`, etc.

3. **Retry and idempotency semantics**
   - Retrying a failed run must not silently duplicate work or corrupt integration outputs.
   - Need per-task retry policy and replay rules.

4. **Observability and auditability**
   - Logs, event traces, adapter decisions, failover reasons, artifact manifests, cost summaries.

5. **Partial-result semantics**
   - The adapter contract has `PARTIAL`, but the proposal says nothing about how Crucible should surface, preserve, validate, or resume from partial outputs.

6. **Chat-side long-run monitoring model**
   - A long-running build cannot depend on a blocking foreground CLI call alone if the user expects chat updates.

### B2. Obvious failure modes not addressed

#### Failure mode: sub-agent completes but CLI misses the event
If `sessions_spawn` completion is push-delivered and the waiting process does not receive the message, what is the source of truth?
- the CLI?
- OpenClaw session transcript?
- a persisted run store?

Right now, unspecified.

#### Failure mode: retry duplicates side effects
A task may:
- create files
- modify a branch
- write artifacts
- run tests
- leave partial outputs

If the orchestrator retries without a task-level idempotency key or workspace isolation model, it may produce duplicate or conflicting state.

#### Failure mode: bad decomposition passes structural checks but fails operationally
Example:
- criterion says "works well"
- verification command is `pytest`
- expected output is `passed`

Technically well-formed. Practically useless.

You need semantic-quality checks, not just non-empty strings.

#### Failure mode: validation success with wrong evidence
Phase 7 already showed this is a real class of risk. Phase 8 should not reintroduce it by letting the skill invent unverifiable criteria or by allowing adapter summaries to stand in for evidence.

#### Failure mode: chat user sees no progress for 10+ minutes
If `crucible run` blocks and only prints final output, the product feels dead even if the engine works.

### B3. Streaming progress UX

Phase 8 needs a concrete UX contract.

Recommended design:
- CLI emits **JSONL events** to stdout with stable schema
- optional human-readable pretty mode for local operators
- OpenClaw skill runs CLI in JSONL mode and converts selected events into concise chat updates
- all events are also persisted to `runs/<run_id>/events.jsonl`

This avoids coupling the CLI to Telegram/OpenClaw formatting while still making it chat-friendly.

### B4. Partial-result handling

Treat partials as first-class.

A task result should carry:
- status: `complete|failed|partial|timed_out|killed`
- artifact manifest
- summary
- remaining blockers
- resumable token or continuation metadata if available

Crucible should not collapse `PARTIAL` into generic failure. It should distinguish:
- partial with usable artifacts
- partial with unusable artifacts
- partial eligible for resume
- partial requiring fresh retry

### B5. Retry policy

Need explicit policy at three levels:

1. **Spawn retry**
   - backend/tooling failure before work starts
   - safe to retry quickly on another backend

2. **Execution retry**
   - agent ran but failed to satisfy criteria
   - only retry if failure class is retryable

3. **Validation retry**
   - evidence incomplete or missing
   - may need re-collection, not full rebuild

Default recommendation for Phase 8:
- spawn failures: retry up to 2 alternate backends
- timeouts: one retry only if task marked retryable
- validation failures: no automatic blind retry; require either better evidence or revised task plan

### B6. Observability

Minimum required artifacts per run:
- run manifest (`run.json`)
- task definitions snapshot (`tasks.json`)
- event stream (`events.jsonl`)
- adapter/failover log
- artifact manifest
- final summary (`result.json`)
- optional cost ledger (`costs.json`)

### B7. Budget / cost tracking

If Crucible is intended to become the default software path, cost discipline becomes mandatory.

Track at least:
- backend used
- wall-clock per task
- retries per task
- token/model metadata if backend can expose it
- count of spawned sub-agents
- estimated cost where exact cost unavailable

Not because billing is the core product — because cost spikes are one of the fastest ways for a “default path” to get turned off.

### B8. Idempotency on retry

This is mandatory.

At minimum:
- every task attempt gets `task_attempt_id`
- workspace path / worktree path must be attributable to that attempt
- integration should merge only outputs from the winning attempt
- retries must not silently re-integrate stale artifact paths

### B9. How does the LLM monitor a long-running orchestrator run from chat?

**Do not rely on polling as the primary model.**

Best production split:
- `crucible run` persists events and exits only when complete if run foregrounded
- `crucible run --detach` starts a durable run and returns `run_id`
- `crucible watch <run_id>` streams events from the persisted event log
- `crucible status <run_id>` returns current state snapshot
- OpenClaw skill uses detached mode for long jobs and periodically or eventfully relays meaningful updates

Within OpenClaw specifically:
- prefer **push-based completion** where available
- supplement with `status` checks against persisted run state, not blind polling of sub-agents

The chat surface should monitor **Crucible run state**, not each sub-agent directly.

---

## C. Sub-agent adapter specifics

### C1. Is wrapping `sessions_spawn` in `BackendAdapter` a clean fit?

**Not cleanly with the current interface.**

The current adapter abstraction assumes the backend can be normalized to:
- spawn
- poll
- collect
- kill

That works for process-like runtimes. OpenClaw sub-agents are closer to **event-driven jobs with asynchronous completion notifications**.

That creates three impedance mismatches:

1. **Status source mismatch**
   - current adapter assumes status can be actively polled
   - OpenClaw sub-agents complete via pushed messages/events

2. **Handle ownership mismatch**
   - current handle is just opaque runtime identity
   - real sub-agents also need session identity, transcript/event linkage, and maybe channel context

3. **Collection semantics mismatch**
   - `collect()` assumes there is a clean terminal result to fetch on demand
   - sub-agent output may arrive incrementally, with intermediate updates and structured completion messages

### C2. Does the current InMemoryAdapter lifecycle fit push-based sub-agents?

**Only as a conceptual reference, not as a semantic match.**

The reference model is useful for parity testing, but it bakes in a polling worldview. If you force push-based sessions into that shape naively, you will end up building a fake poller on top of an event stream.

That is acceptable only if you introduce an internal **event-backed state machine** behind the adapter.

### C3. How do you bridge async push completion into synchronous `Router.execute_with_fallback()`?

There are two options.

#### Option 1: bridge layer under the existing sync router
- adapter spawns sub-agent
- adapter also creates durable local run record
- incoming sub-agent events update local adapter state
- `poll()` reads the locally persisted state snapshot
- `collect()` reads the terminal result from that state

This preserves the current interface, but the adapter is no longer truly polling the backend — it is polling its own event-backed cache.

This is the fastest path to productionization **without rewriting Router in Phase 8**.

#### Option 2: make router execution async-first
- `spawn()` returns immediately
- adapter exposes awaitable completion or event subscription
- router becomes async and orchestrator can interleave execution/progress naturally

This is architecturally cleaner long-term, but too large for a minimal Phase 8 unless you are explicitly willing to refactor orchestrator and router signatures.

### C4. Should the adapter be async-first instead?

**Long-term: yes. Phase 8: not necessarily.**

My recommendation:
- **Phase 8 MVP:** keep the current sync `BackendAdapter` contract, but implement the OpenClaw adapter as an **event-backed sync facade**
- **v5.3 spec update:** explicitly mark current adapter ABI as transitional and introduce a roadmap for async/event-native backends
- **future phase:** add `AsyncBackendAdapter` or an event-stream execution interface

That gets you a real shipping path without destabilizing the whole library now.

### C5. Concrete adapter design recommendation

Implement `OpenClawSubagentAdapter` with:
- `spawn(spec)`
  - starts sub-agent session
  - persists adapter-local run record keyed by handle ID
  - stores mapping: `handle_id -> subagent_session_id`
- event ingestor
  - consumes push completion/progress messages
  - updates local persisted status/result
- `poll(handle)`
  - reads persisted adapter state
- `collect(handle)`
  - returns materialized `AdapterRunResult` from persisted terminal state
- `kill(handle)`
  - sends cancel/terminate if supported, otherwise marks kill-requested and records unsupported semantics explicitly

Also extend `AdapterRunResult` or metadata to include:
- `attempt_id`
- `backend_run_id` / `session_id`
- `partial_artifact_paths`
- structured error class

---

## D. Skill registration

### D1. Is `SKILL.md` the right surface?

**Yes.**

That is the correct OpenClaw-native discovery surface. If the goal is “make Crucible the first thing the agent reaches for on multi-step software work,” skill selection is the control plane.

### D2. Should there also be a `TOOLS.md` entry?

**Yes, but not as the primary activation surface.**

Use `TOOLS.md` only for local operator notes such as:
- where Crucible repo lives
- preferred CLI invocation
- workspace assumptions
- detached-run conventions
- default output paths

Do not rely on `TOOLS.md` for behavior. The behavioral contract belongs in `SKILL.md` and Crucible itself.

### D3. How sharp does the skill description need to be?

**Extremely sharp.**

If the description is too broad, Crucible will fire on trivial edits and slow the system down.
If too narrow, it will never activate.

The description should explicitly target:
- multi-step software implementation
- bug fixes requiring decomposition, verification, and integration
- refactors spanning multiple files/components
- tasks where acceptance criteria and validation matter
- work that benefits from deterministic retry / validation / integration tracking

It should explicitly exclude:
- one-line edits
- pure code reading
- simple shell commands
- ad hoc research
- isolated file patching with no decomposition needed

### D4. Trigger phrases that should activate Crucible

Should activate:
- “build X feature”
- “implement X end to end”
- “fix this bug and add tests”
- “refactor this subsystem safely”
- “ship a first working version”
- “decompose this software task and execute it”
- “make this production-ready”
- “write the module, tests, and integrate it”

Should not activate:
- “open this file”
- “explain this code”
- “rename this variable”
- “change one string”
- “run this command”
- “summarize this PR”
- “grep where this function is used”

### D5. Recommendation for skill body behavior

The skill should not simply say “decompose then run.” It should include guardrails:

1. determine whether task complexity justifies Crucible
2. produce structured task definitions using approved templates
3. validate task definitions locally before invoking CLI
4. invoke `crucible run` in JSON mode
5. surface only meaningful progress updates to chat
6. on failure, distinguish:
   - decomposition defect
   - backend execution defect
   - validation defect
   - integration defect

That separation matters for operator trust.

---

## E. Decomposition layer

### E1. Natural language → TaskDefinition is genuinely hard

Yes. This is the most underestimated part of the proposal.

The core risk is that the LLM will produce criteria that are:
- vague
- duplicated
- not independently verifiable
- not scoped to a single task
- not tied to executable verification
- weakly coupled to delivered artifacts

A production harness cannot accept those blindly.

### E2. Should Crucible reject poor TaskDefinitions before execution?

**Absolutely yes. Mandatory.**

Crucible already enforces verification-triple well-formedness at validation time. That is too late.

You need a **preflight intake validator** for task definitions before any task is dispatched.

It should reject:
- empty or duplicate task IDs
- empty descriptions
- no criteria
- no must-pass criteria
- malformed verification triples
- vague descriptions and vague expected outputs
- criteria whose verification command is clearly unrelated to the stated deliverable
- criteria with generic expected outputs like `success`, `works`, `done`, `passes` unless contextualized
- criteria that share identical triples while claiming different objectives

### E3. What should “vague” mean operationally?

Do not rely on a fuzzy vibe check. Add concrete heuristics.

Examples of rejectable patterns:
- expected output shorter than a minimum useful threshold unless from an allowlist
- descriptions containing weak language like `works well`, `properly`, `as expected` without measurable condition
- verification command missing target specificity where specificity is required
- build target like `project` or `code` instead of concrete file/module/test target

This can be heuristic and still useful.

### E4. Should the skill provide examples/templates?

**Yes. Strongly recommended.**

The skill should ship templates for at least four common task shapes:

1. **Build feature**
   - implement files
   - add tests
   - run targeted verification
   - integrate

2. **Fix bug**
   - reproduce bug with failing test
   - patch implementation
   - prove regression fixed

3. **Refactor**
   - preserve behavior
   - add/retain tests
   - verify no API drift unless intended

4. **Write tests / harden coverage**
   - identify missing path
   - add tests
   - verify failure before / pass after if possible

These templates should include good and bad examples of criteria and verification triples.

### E5. Recommended Phase 8 decomposition contract

Add a schema layer such as:
- `TaskDefinitionInput`
- `TaskDefinitionLintResult`
- `TaskDefinitionNormalizationResult`

This keeps the decomposition validator independent from the runtime orchestrator.

---

## F. Better alternatives

### F1. CLI vs MCP server vs HTTP API vs Python-only API

#### CLI
**Best Phase 8 choice.**

Why:
- easiest to invoke from OpenClaw skill/tooling
- stable operator surface
- simple local debugging
- supports detached/background execution and machine-readable output
- keeps library usable outside OpenClaw

#### Python-only API via `exec`
Good for internal testing, bad as the primary production surface.

Why not primary:
- no durable contract
- awkward for external orchestration
- encourages ad hoc scripts instead of a stable runtime boundary

#### HTTP API
Potentially useful later, not first.

Why not first:
- introduces server lifecycle, auth, port management, deployment questions
- overkill for local single-host adoption

#### MCP server
Interesting, but **not the first productionization move**.

Why:
- good for tool-discoverable invocation
- not ideal as the first runtime boundary for long-running orchestrated jobs
- still needs the same lifecycle, durability, and event model underneath

If you build MCP first, you may just end up wrapping the CLI or library anyway.

### F2. Should Crucible become an OpenClaw plugin instead of a separate library + skill?

**No. Not yet.**

Making Crucible an OpenClaw plugin too early would be a category mistake.

Crucible's core value is that it is a **harness engine**, not an OpenClaw-specific extension. If you collapse it into plugin form now, you couple:
- runtime model
- discovery model
- session semantics
- deployment assumptions

That weakens portability and makes the architecture narrower, not stronger.

Keep Crucible as:
- Python library at the core
- CLI as stable runtime surface
- OpenClaw skill as adoption layer
- OpenClaw-backed adapter as one backend implementation

### F3. What would a Crucible-native OpenClaw integration look like?

A stronger long-term integration would include:
- native OpenClaw tool or plugin exposing `crucible.run`, `crucible.status`, `crucible.watch`, `crucible.resume`
- direct event delivery from Crucible into OpenClaw updates
- sub-agent adapter speaking OpenClaw job/session semantics natively
- skill scanner selecting Crucible by default for qualifying software tasks
- structured run objects visible to the chat layer, not just CLI text

But that is **Phase 9+**, not required for Phase 8 signoff.

### F4. So what is the better alternative to the current proposal?

Not a different architecture. A stricter version of the same one.

The correct adjustment is:
- **CLI + skill + adapter stays**
- add **durable run/state/event layer** now
- defer native plugin/MCP/server until after the operational model is proven

---

## G. Concrete recommendation

### G1. What Phase 8 should actually contain

Phase 8 should contain **six** deliverables, not four.

#### 1. `crucible.cli` with machine-readable modes
Required commands:
- `crucible run`
- `crucible status <run_id>`
- `crucible watch <run_id>`
- `crucible resume <run_id>`

Required output modes:
- human-readable
- JSON / JSONL event stream

#### 2. `OpenClawSubagentAdapter`
A real adapter wrapping OpenClaw sub-agents, but implemented as an **event-backed sync facade** over the existing adapter ABI.

#### 3. Durable run store
Persist under a predictable path, e.g.:
- `runs/<run_id>/run.json`
- `runs/<run_id>/tasks.json`
- `runs/<run_id>/events.jsonl`
- `runs/<run_id>/result.json`

This is the missing productionization layer.

#### 4. TaskDefinition preflight validator / linter
Reject poor decomposition before execution.

#### 5. OpenClaw `crucible` skill
With:
- sharp activation description
- when-to-use / when-not-to-use
- decomposition templates
- guidance for retry/blocker surfacing

#### 6. Validation suite beyond one smoke test
You need at least:
- happy path smoke test
- restart/resume test
- partial-result test
- timeout + retry test
- malformed decomposition rejection test
- failover audit test

### G2. Minimum viable productionization

If you want the smallest shippable Phase 8, it is:
- `crucible run`
- `crucible status`
- persisted run store
- `OpenClawSubagentAdapter`
- task-definition validator
- one skill
- two end-to-end tests:
  - happy path
  - restart/resume

Anything less is a demo, not productionization.

### G3. Gold-standard version

Gold-standard Phase 8 would include:
- full CLI lifecycle (`run/status/watch/resume/cancel`)
- event schema + persisted event logs
- async-capable adapter internals
- cost ledger
- decomposition linter with templates and examples
- detached mode for chat-native long jobs
- rich e2e test matrix with real OpenClaw session simulation
- observability packet for each run

### G4. Right ordering

Recommended implementation order:

1. **Run model + CLI scaffolding**
   - define run IDs, manifests, persisted event schema
2. **TaskDefinition intake validator**
   - fail weak decompositions before runtime work begins
3. **OpenClawSubagentAdapter**
   - bridge push events into persisted adapter state
4. **CLI lifecycle commands**
   - `run`, `status`, `watch`, `resume`
5. **OpenClaw skill**
   - use templates and machine-readable CLI modes
6. **End-to-end validation suite**
   - prove restart safety, partial semantics, and chat monitoring model

Do **not** start with the skill. If the runtime boundary is weak, the skill will just expose the weakness faster.

### G5. Gates before Phase 8 signoff

Phase 8 should not pass without the following gates:

#### Runtime gates
- can start a run and retrieve a durable `run_id`
- can recover run state after process restart
- can surface terminal result from persisted state
- retries do not duplicate integration artifacts

#### Adapter gates
- OpenClaw adapter preserves semantic parity with `BackendAdapter`
- push completion is reflected in adapter state without race-induced false failure
- timeout / partial / failure states map cleanly into `AdapterStatus`

#### Decomposition gates
- malformed or vague task definitions are rejected preflight
- criteria require at least one must-pass verification contract
- duplicate or orphan criterion definitions are rejected

#### UX gates
- a long-running run emits meaningful progress events
- chat layer can monitor a run without direct sub-agent polling
- final output distinguishes decomposition, execution, validation, and integration failures

#### Evidence gates
- validation still requires real evidence and registry-backed provenance
- no adapter summary text can satisfy criterion completion by itself

#### E2E gates
- fizzbuzz-class smoke test
- restart mid-run and resume successfully
- forced backend failure with failover recorded durably
- partial result preserved and surfaced

---

## Specific concrete recommendations for Phase 8 scope

1. **Keep the proposed four deliverables, but expand Phase 8 scope explicitly**
   - CLI
   - adapter
   - skill
   - smoke test
   - plus durable run store
   - plus task-definition validator

2. **Do not put natural-language planning inside Crucible yet**
   - keep planning in the skill
   - enforce structure in Crucible

3. **Do not rewrite Router/Orchestrator async in Phase 8**
   - bridge OpenClaw push events behind a sync facade first
   - document async-native adapter evolution as future work

4. **Make run/event persistence non-optional**
   - this is the difference between “usable” and “demo”

5. **Treat `PARTIAL` as a real state, not a synonym for failure**
   - preserve artifacts
   - expose blockers
   - enable resume or explicit restart

6. **Add task-definition linting examples into the skill**
   - build feature
   - fix bug
   - refactor
   - write tests

7. **Ship `status` and `watch` with `run`**
   - otherwise OpenClaw chat monitoring will be awkward and fragile

8. **Record adapter failover and backend selection decisions in run events**
   - not only in router-local state

---

## Suggested updates to the spec (v5.2 → v5.3)

### 1. Add a new phase or subphase for production runtime surface
Suggested wording:

- **Phase 8: Production runtime surface and OpenClaw embedding**
  - CLI lifecycle surface (`run/status/watch/resume`)
  - durable run manifests and event logs
  - OpenClaw-backed accelerator adapter
  - skill registration and task decomposition templates
  - end-to-end operational validation

### 2. Add a formal run/event model
Define:
- `RunManifest`
- `RunEvent`
- `TaskAttemptRecord`
- `RunSummary`

Include required persisted fields:
- run ID
- project/build IDs
- task definitions snapshot
- current phase
- backend selections / failovers
- artifact manifest
- final status

### 3. Add preflight decomposition validation
Spec should say:
- Crucible may accept externally generated task definitions
- but must reject task plans that are structurally invalid, operationally vague, or unverifiable

### 4. Clarify adapter evolution path
Add language that current backend adapter API is sufficient for pollable runtimes, but event-driven runtimes may require:
- persisted state bridge, and/or
- future async-native adapter interface

### 5. Add explicit partial/resume semantics
Define:
- what `PARTIAL` means
- whether partial artifacts are valid for validation
- when resume is allowed
- when fresh retry is required

### 6. Add observability requirements
For any production run, require persisted:
- event log
- adapter/failover trace
- artifact manifest
- final summary

### 7. Add chat-surface monitoring guidance
The spec should explicitly separate:
- backend execution monitoring
- harness run monitoring

OpenClaw should monitor **Crucible run state**, not raw backend sessions.

### 8. Add decomposition templates to the embedding guidance
Spec should include canonical examples for:
- feature build
- bug fix
- refactor
- test-writing task

This reduces plan-quality drift across models.

---

## Final recommendation

The proposal is **directionally right and should proceed**, but not in its current thin form.

If you ship only:
- CLI
- adapter
- skill
- smoke test

then you will have a persuasive demo and a weak operational substrate.

If you ship:
- CLI
- adapter
- durable run/event store
- decomposition validator
- skill
- restart/partial/failover tests

then you will have the first credible version of Crucible as a real default execution path inside OpenClaw.

That is what Phase 8 should be.
