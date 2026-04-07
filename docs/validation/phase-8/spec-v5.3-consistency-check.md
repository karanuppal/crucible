# Spec Consistency Check — Crucible v5.3

Overall verdict: READY WITH CLARIFICATIONS

v5.3 is directionally correct and captures the core productionization recommendations from the review. I would sign off on it as the basis for Phase 8 only after a small set of contract clarifications are made. The current draft is not fundamentally wrong, but it still has a few internal mismatches and underspecified boundaries that will create avoidable implementation churn if left unresolved.

The biggest themes:
- The new production runtime surface fits the existing Phase 1-7 architecture better as an augmentation layer than a replacement.
- The durable run store should sit above the existing Phase 1 ledger, not replace it.
- The OpenClaw adapter concept is sound, but §28 alone is not specific enough to implement without reading existing adapter/router code.
- The CLI and preflight validator are close, but both need explicit I/O contracts.
- One real blocker remains: the spec currently references statuses/events that do not exist in the existing ABI (`unknown` attempt state) and leaves the run/orchestrator mapping implicit.

---

## 1. Internal consistency

### 1.1 Does the v5.3 addendum contradict anything in v5.2 §1-§24 above it?

Mostly no. The addendum is largely additive and consistent with the v5.2 spine:
- v5.2 already wants deterministic state, durable continuity, append-only events, resumable long-running work, and sub-agent-first execution.
- v5.3 adds the missing operator/runtime surface to make that architecture actually usable from chat.
- The split in §25.2 matches v5.2's layer model in §5 and OpenClaw portability stance in §18.

But there are four notable inconsistencies.

#### Finding A — phase numbering is internally inconsistent
- v5.2 §20 says: "The implementation can be staged in six phases."
- v5.3 is labeled "Production Runtime Surface (Phase 8)"
- The existing source tree clearly has Phase 7 concepts already implemented (`orchestrator/`, top-level glue layer).

This means the spec document itself does not explain how we got from 6 planned phases to Phase 8.

Impact:
- Not a design flaw, but it makes implementation planning and signoff sloppy.

Recommendation:
- Amend §20 or add a short note near the v5.3 addendum that Phase 7 corresponds to the orchestrator/integration glue layer already landed in code, and v5.3 defines Phase 8 on top of that.

#### Finding B — v5.3 claims to supersede the wrong sections
The header says:
- "Active (supersedes v5.2 §1, §22 where they conflict)"

But the meaningful areas affected are not §1 and §22. The actual overlap is with:
- §10 Execution Backend Interface
- §11 State, Ledger, and Artifact Model
- §20 Implementation Plan

Impact:
- Readers will miss where the new runtime contract modifies prior assumptions.

Recommendation:
- Update the supersession note to reference the sections that actually overlap.

#### Finding C — command/output model is slightly self-contradictory
§25.3 says:
- "All commands MUST support ... JSONL event streaming"

That makes sense for `run` and `watch`, but not literally for `status`, which is defined one line earlier as:
- "snapshot of current run state"

Impact:
- Minor, but it creates needless CLI ambiguity.

Recommendation:
- Distinguish snapshot-style JSON output from streaming JSONL output.

#### Finding D — `unknown` appears in restart semantics but not in any declared status enum
§26.3 says:
- "Partial task attempts that did not record a terminal state MUST be marked `unknown`"

But:
- `TaskAttemptRecord.status` is `AdapterStatus`
- existing `AdapterStatus` in `src/crucible/accelerators/adapters.py` is only: `PENDING | RUNNING | COMPLETE | FAILED | KILLED | TIMED_OUT | PARTIAL`
- existing `RunStatus` in `src/crucible/state/models.py` also has no `UNKNOWN`

Impact:
- This is a real contract mismatch.
- Implementers cannot represent the mandated post-crash state without inventing behavior.

Recommendation:
- Either add `UNKNOWN` to the declared status domain, or change the restart rule to say the attempt remains non-terminal with a separate recovery flag like `recovery_status: "unknown"` or `needs_reconciliation: true`.

### 1.2 Are the new contracts self-consistent?

Partially. They are close, but not fully locked down.

#### RunManifest
What works:
- Clean top-level identity and embedding metadata.
- `project_id`, `build_id`, `current_phase`, and `current_status` fit the orchestrator concept.

What is underspecified:
- No explicit `run_root` / storage path.
- No pointer to task attempts, artifact manifest, or adapter state.
- `current_status` is a separate vocabulary from `AdapterStatus` and `RunStatus`, but the mapping is not defined.

Verdict:
- Usable, but should explicitly define status mapping and one-to-one relationship to an Orchestrator instance.

#### RunEvent
What works:
- It captures the review's recommendation for a first-class event stream.
- Event types cover the main operational lifecycle.

What is underspecified or inconsistent:
- No `run_failed`, `run_partial`, or `run_resumed` event types.
- `run_completed` appears to be the only terminal run event, even though `RunManifest.current_status` allows `failed` and `partial`.
- `subagent_event` payload is fully opaque, but no minimum required payload shape is defined.

Verdict:
- Not fully self-consistent yet. The terminal event vocabulary needs to align with the allowed run/task statuses.

#### TaskAttemptRecord
What works:
- Good attempt identity model (`task_id + attempt_index`).
- Correctly carries artifacts, timing, error, and resume token.

What is underspecified or inconsistent:
- `status: AdapterStatus` conflicts with the `unknown` restart rule.
- No `attempt_index` field despite the identity rule depending on it.
- No winning/losing attempt marker despite §26.4 depending on "winning attempt" semantics for integration.
- No worktree/scratch path field even though workspace isolation is mandated by attempt id.

Verdict:
- Good skeleton, not enough for implementation as written.

#### RunSummary
What works:
- Correct top-level reporting fields.

What is underspecified:
- `terminal_status: enum` is not enumerated.
- `integration_status: string?` is too loose compared with existing typed integration state.
- `cost_summary: CostSummary?` references a type that is not defined anywhere in the spec.

Verdict:
- Needs tightening before someone codes it directly.

### 1.3 Does the run model fit on top of the existing Phase 1 ledger or duplicate it?

It overlaps, but it should be treated as an augmentation, not a replacement.

What exists today:
- `ledger/ledger.py` already provides append-only JSONL events at the project/build/task/run level.
- It records events like `spec.created`, `task.created`, `run.spawned`, `validation.completed`, `integration.completed`, `build.completed`.

What v5.3 adds:
- a per-run operational packet under `runs/<run_id>/`
- richer runtime events tied to one invocation
- durable restart/resume surface
- adapter trace and artifacts bundle

Conclusion:
- The new run store should not replace the Phase 1 ledger.
- It should sit beside it.
- Best model: the ledger remains the cross-build, project-level audit log; the run store becomes the per-invocation execution packet.

Recommended relationship:
- Ledger = global/project chronology.
- Run store = local/run chronology and resumability substrate.
- Important run-store events should also be mirrored or summarized into the project ledger when they matter at project scope.

### 1.4 Does the sub-agent adapter fit the existing Phase 6 BackendAdapter ABI cleanly?

Conceptually yes. Concretely only with a bridge layer.

The existing ABI in `src/crucible/accelerators/adapters.py` is:
- `spawn(spec) -> AdapterRunHandle`
- `poll(handle) -> AdapterStatus`
- `collect(handle) -> AdapterRunResult`
- `kill(handle) -> None`

The existing router in `src/crucible/accelerators/router.py` assumes:
- polling loop until non-running state
- then `collect`
- then failover based on terminal status

That matches the review's assessment exactly: the adapter can fit only as an event-backed sync facade.

What fits cleanly:
- `spawn` can create the OpenClaw sub-agent and persist the handle→session map.
- `poll` can read the local persisted adapter state.
- `collect` can materialize a final `AdapterRunResult`.

What does not fit cleanly yet:
- Existing `AdapterRunResult` has only `artifact_paths`, `summary`, `error`, timestamps. It has no place for:
  - OpenClaw session id
  - event refs
  - partial blockers
  - resume token
  - kill unsupported note
- §28.4 says these go in "metadata," but current `AdapterRunResult` has no metadata field.

Conclusion:
- The adapter model is viable.
- The spec correctly chooses the bridge approach.
- But the ABI extension points need to be named explicitly, otherwise implementers will have to silently mutate Phase 6 contracts.

---

## 2. Reviewer fidelity

### 2.1 Does v5.3 capture every recommendation from the productionization review?

It captures almost all of them.

Clearly preserved from the review:
- CLI as primary runtime surface
- durable run IDs and persisted run store
- persisted event stream
- `status` / `watch` / `resume`
- OpenClaw adapter as event-backed sync facade
- decomposition stays in skill, but Crucible validates it
- preflight validator with heuristic rejection
- partial-result preservation
- observability artifacts
- chat surface monitors Crucible run state, not raw backends
- broader E2E matrix, not just a smoke test
- async-native adapter explicitly deferred

### 2.2 Anything dropped that should have been kept?

Yes, three things are still materially underrepresented.

#### Dropped / weakened item 1 — explicit retry policy tiers
The review recommended separate semantics for:
- spawn retry
- execution retry
- validation retry

v5.3 preserves idempotency and failover, but it does not specify default retry rules.

Impact:
- Implementers will invent different retry behavior in router/orchestrator/CLI.

Recommendation:
- Add a short normative subsection defining default retry policy for Phase 8.

#### Dropped / weakened item 2 — artifact manifest as a formal file
The review called for a durable artifact manifest.

v5.3 says:
- `artifacts/` in §26.1
- `artifacts/ — manifest of all produced artifacts with content hashes` in §30

But no explicit file is defined.

Impact:
- It is unclear whether `artifacts/` is a directory, a manifest, or both.

Recommendation:
- Define `artifacts/` as a directory and `artifacts.json` as the manifest.

#### Dropped / weakened item 3 — source of truth for missed push completion
The review explicitly called out the failure mode: sub-agent completes but CLI misses the push event.

v5.3 implies persisted state is the answer, but does not explicitly state the authoritative source of truth for adapter reconciliation.

Impact:
- Adapter implementation may end up depending on transient process-local listeners.

Recommendation:
- State explicitly that persisted adapter state under the run store is authoritative for `poll`/`collect`, and define how reconciliation happens on restart.

### 2.3 Anything added beyond the review's scope?

A little, but nothing harmful.

Added beyond the review:
- specific install path for the skill (`~/.openclaw/workspace/skills/crucible/SKILL.md`)
- slightly stronger normative wording around TOOLS.md
- explicit non-goals list for HTTP/MCP/plugin/cancel

These are reasonable scope-sharpening additions, not spec drift.

---

## 3. Buildability

## 3.1 Is Phase 8 actually buildable from this spec?

Mostly buildable, but not buildable cleanly from the new sections alone. The Phase 8 implementation is buildable if the implementer also reads the existing Phase 1-7 code. If the intent is that §25-§32 alone should be sufficient, the answer is no.

### 3.2 Can someone implement the OpenClaw adapter from §28 alone?

No.

What §28 gives you:
- the architecture pattern
- the method behaviors at a high level
- the compatibility intent

What it does not give you:
- the actual `BackendAdapter` and `AdapterRunResult` field definitions
- the exact terminal `AdapterStatus` set
- how OpenClaw push messages arrive to the adapter process
- required persisted adapter-state schema
- how to represent metadata not present on `AdapterRunResult`
- timeout ownership: router loop vs adapter ingestor vs CLI supervisor

The adapter is implementable only by reading existing code in:
- `src/crucible/accelerators/adapters.py`
- `src/crucible/accelerators/router.py`

Verdict:
- Buildable in project context, not from §28 alone.

### 3.3 Can someone implement the run store from §26 alone?

Not quite.

Missing pieces:
- canonical root path for `runs/`
- atomic write rules for `run.json`, `result.json`, and `events.jsonl`
- exact relationship between `TaskAttemptRecord` and files on disk
- where attempt records live
- authoritative artifact manifest file
- whether `run.json` is mutable in place or append-only snapshot-derived
- how `resume` discovers in-flight attempts

Verdict:
- The schema direction is good, but §26 alone is insufficient for two independent implementers to build compatible stores.

### 3.4 Can someone implement the preflight validator from §27 alone?

Almost, but still no.

What is missing:
- the canonical `TaskDefinition` schema for intake
- the canonical `VerificationTriple` field names at the intake boundary
- whether normalization is allowed to rewrite IDs or only whitespace/formatting
- concrete `LintFinding` schema
- whether warnings ever block

There is also a mismatch with existing code:
- existing `TaskDefinition` in `orchestrator/orchestrator.py` has `task_id`, `description`, `criteria`, `role`, `intensity_hint`, `spec_command`
- existing `Criterion.VerificationTriple` in `validation/criterion.py` uses `build_target`, `verification_command`, `expected_output`, `failure_signature`
- v5.2 prose in §8.3 describes the triple semantically, not structurally

Verdict:
- One engineer could implement it, but only by inferring missing schemas from code.
- If the goal is independent buildability from the spec, it needs a formal intake schema.

### 3.5 Does the CLI surface in §25.3 specify enough to build?

No.

Missing CLI details:
- input format for `crucible run` (file path? stdin? JSON? YAML?)
- output mode flags (`--json`, `--jsonl`, `--human`?)
- detach flag syntax and detached-run behavior
- exit code semantics
- whether `watch` replays prior events or only tails new ones
- whether `resume` is idempotent if the run is already active
- whether `status` returns manifest-only info or derived attempt/task summaries too

Verdict:
- The command set is correct.
- The operator contract is not complete enough yet to code against blindly.

### 3.6 Does the skill contract in §29 specify enough to write SKILL.md?

Almost, but still not fully.

What is sufficient:
- activation boundary
- when-to-use / when-not-to-use intent
- templates category list
- high-level LLM responsibilities

What is not sufficient:
- no example trigger wording
- no required decomposition output format example
- no exact local invocation for the lint step
- no example chat update policy
- no good/bad criterion examples, despite saying they must exist

Verdict:
- Enough to draft SKILL.md.
- Not enough to ensure two people would write the same skill behavior.

---

## 4. Integration with Phase 1-7

### 4.1 Does the new run store overlap or conflict with the existing Phase 1 Ledger?

Overlap: yes.
Conflict: not if scoped correctly.

Current code reality:
- The ledger is append-only, project/build-oriented, and intentionally generic.
- The orchestrator already emits major lifecycle events into it.
- The run store proposed in v5.3 is a finer-grained per-run runtime packet.

The clean model is:
- Keep the Phase 1 ledger as the cross-run system of record for meaningful project/build events.
- Add the Phase 8 run store as the detailed execution record for one `crucible run` invocation.
- Mirror a subset of run-store events into the ledger when they matter at project scope.

Do not replace the ledger with `events.jsonl`.
That would regress the project-level continuity model already established in v5.2.

### 4.2 How should an Orchestrator instance map to a RunManifest?

It should be one-to-one.

Recommended mapping:
- one `crucible run` invocation creates one `RunManifest`
- that manifest corresponds to one top-level Orchestrator instance
- child task attempts remain within that run unless explicitly detached into their own top-level run

Concrete mapping:
- `RunManifest.run_id` = top-level orchestrator invocation id
- `RunManifest.project_id` / `build_id` = orchestrator identifiers
- `RunManifest.current_phase` = serialized `OrchestratorState.current_phase`
- `RunSummary` = terminal projection of `OrchestratorState`
- `TaskAttemptRecord`s = execution-level expansions under the orchestrator's tasks

The spec should say this explicitly.

### 4.3 Should the Phase 1 Ledger be replaced, augmented, or kept separate?

Augmented, not replaced.

Best design:
- keep both
- ledger is coarse-grained and cross-run
- run-store `events.jsonl` is fine-grained and run-local
- provide deterministic cross-links:
  - ledger event payloads may include `run_id`
  - run-store manifest should include `ledger_ref` or equivalent pointer if a project ledger exists

### 4.4 Does the durable run store create state that conflicts with existing OrchestratorState?

Not inherently, but it duplicates some fields unless ownership is clarified.

Existing `OrchestratorState` already has:
- `project_id`
- `build_id`
- `spec_text`
- `current_phase`
- `blocked_reason`
- `completed_tasks`
- `failed_tasks`
- integration artifact paths

`RunManifest` / `RunSummary` repeat much of this.

Recommended ownership split:
- `OrchestratorState` = in-memory working state and resume payload for orchestrator logic
- `RunManifest` = durable external snapshot of orchestrator state for CLI/status/watch
- `RunSummary` = durable terminal projection for operators

Without that explicit split, implementers may create two diverging truths.

---

## 5. Open questions

### BLOCKER

#### 1. What is the canonical status model for crash-recovery reconciliation?
Problem:
- §26.3 requires `unknown`
- existing `AdapterStatus` / `RunStatus` do not contain it

Must decide:
- add `UNKNOWN` to the status enums, or
- represent recovery uncertainty separately from terminal/non-terminal status

Why blocker:
- restart/resume logic cannot be implemented cleanly without this.

#### 2. What is the exact mapping between top-level Orchestrator runs and RunManifest?
Problem:
- one-to-one is strongly implied but never stated

Must decide:
- whether each `crucible run` always creates exactly one top-level orchestrator-backed `RunManifest`
- whether child runs ever get independent manifests

Why blocker:
- this affects storage layout, status semantics, and resume behavior.

#### 3. What is the formal intake schema for `crucible run`?
Problem:
- §25 and §27 rely on a structured task plan, but the input contract is not defined

Must decide:
- stdin vs file vs arg
- JSON vs YAML vs both
- exact `TaskDefinition` schema
- exact lint result schema

Why blocker:
- CLI, skill, and validator cannot be implemented against a stable contract otherwise.

#### 4. Where does adapter-local persisted state live, and what is authoritative after restart?
Problem:
- §28 requires persisted adapter state, but its location/schema/authority are unstated

Must decide:
- whether adapter state is part of `runs/<run_id>/`
- whether `poll` and `collect` read only that state after restart
- how missed push events are reconciled

Why blocker:
- the OpenClaw adapter cannot be built safely without this.

### CLARIFICATION

#### 5. What are the exact CLI output modes?
Need:
- snapshot JSON vs streaming JSONL distinction
- exit codes
- `watch` replay/tail semantics

#### 6. What are the exact terminal event types for `RunEvent`?
Need:
- whether to add `run_failed`, `run_partial`, `run_resumed`
- minimum payload schemas per event type

#### 7. What is the artifact manifest file called?
Need:
- explicit file, likely `artifacts.json`
- relation to `artifacts/` directory

#### 8. What fields belong on `TaskAttemptRecord` beyond the current skeleton?
Likely needed:
- `attempt_index`
- `workspace_path` or `worktree_ref`
- `winning_attempt: bool`
- `blockers: list[str]`

#### 9. What Phase 8 retry policy is normative?
Need:
- spawn retry count
- timeout retry behavior
- validation retry behavior

#### 10. How much of the skill contract is normative vs illustrative?
Need:
- whether examples/templates are required artifacts
- whether good/bad examples must live in SKILL.md or may live beside it

---

## Section-by-section findings

### §25 Production Runtime Surface
- Correct direction and faithful to the review.
- CLI command set is right.
- Not sufficiently specified to build the CLI without additional contract details.
- `status` vs JSONL streaming wording should be tightened.

### §26 Durable Run Model
- Strongest addition in the addendum.
- Correctly introduces persistent run identity and resumability.
- Needs explicit status vocabulary, authoritative storage semantics, and artifact manifest file.
- `TaskAttemptRecord` is underdefined for retry/workspace isolation.

### §27 TaskDefinition Preflight Validator
- Correct and necessary.
- Fits existing Phase 3 validation philosophy well.
- Needs a formal input schema and lint result schema to be independently buildable.
- Also needs an invocation contract if the skill is supposed to run it locally.

### §28 OpenClaw Sub-agent Adapter
- Right architecture choice.
- Fits existing Phase 6 design only via a persisted bridge layer.
- Not sufficient on its own to build against without reading existing adapter/router code.
- Needs an explicit ABI extension story for metadata/session refs/partial blockers.

### §29 Skill Contract
- Directionally right and appropriately bounded.
- Good activation guardrail.
- Enough for a first draft, not enough for a fully reproducible SKILL.md.
- Missing exact lint invocation and example decomposition payload.

### §30 Observability Requirements
- Faithful to the review.
- Needs one more concrete artifact: explicit artifact-manifest filename and schema.

### §31 Chat-Surface Monitoring Model
- Correct and important.
- Good separation: monitor Crucible state, not raw sub-agents.
- Needs exact `--detach` CLI behavior and watch/status semantics.

### §32 Validation Matrix
- Good gating section.
- Matches the review closely.
- One mismatch: decomposition blocking gates mention duplicate / orphan criterion definitions, but §27 only explicitly defines duplicate and cross-task collision checks; orphan handling is inherited from validator behavior, not intake schema. Worth making explicit.

---

## Specific edits to v5.3 spec if needed

### Edit 1 — fix supersession note
Quote:
- `**Status:** Active (supersedes v5.2 §1, §22 where they conflict)`

Proposed change:
- `**Status:** Active addendum (supersedes or refines v5.2 §10, §11, §20, and §22 where they conflict)`

Why:
- Those are the sections actually affected by the new runtime surface.

### Edit 2 — fix phase numbering ambiguity
Quote:
- `# v5.3 Addendum — Production Runtime Surface (Phase 8)`

Proposed change:
- `# v5.3 Addendum — Production Runtime Surface (Phase 8)`
- Add immediately below: `Phase 7 corresponds to the orchestrator/integration glue layer already implemented in the codebase; this addendum defines the next phase after that existing Phase 1-7 baseline.`

Why:
- The current document otherwise jumps from a six-phase plan to "Phase 8" with no explanation.

### Edit 3 — split snapshot JSON from streaming JSONL
Quote:
- `All commands MUST support:`
- `- Human-readable output (default for terminal use)`
- `- JSONL event streaming (default when invoked from a skill / scripted surface)`

Proposed change:
- `All commands MUST support machine-readable output.`
- `Streaming commands (` + "`run`, `watch`" + `) MUST support JSONL event output.`
- `Snapshot commands (` + "`status`, terminal `resume` output" + `) MUST support structured JSON output.`
- `Human-readable output remains the default for terminal use.`

Why:
- `status` is a snapshot, not an event stream.

### Edit 4 — resolve `unknown` status mismatch
Quote:
- `Partial task attempts that did not record a terminal state MUST be marked ` + "`unknown`" + ` and either retried or surfaced as blockers, never silently treated as success`

Proposed change:
Option A:
- `TaskAttemptRecord.status` adds `UNKNOWN` to the declared status domain.`

Option B:
- Replace the sentence with: `Partial task attempts that did not record a terminal state MUST remain non-terminal and be marked with ` + "`needs_reconciliation: true`" + ` until resume logic classifies them as retriable, blocked, or terminal.`

Why:
- Current spec references a state that does not exist in the declared ABI.

### Edit 5 — make run/orchestrator mapping explicit
Quote:
- `RunManifest {`

Proposed addition inside or immediately below `RunManifest`:
- `One top-level Orchestrator instance maps 1:1 to one RunManifest created by ` + "`crucible run`" + `. Child task attempts do not create independent top-level manifests unless explicitly detached into a new top-level run.`

Why:
- This is currently implicit but architecturally important.

### Edit 6 — complete `TaskAttemptRecord`
Quote:
- `TaskAttemptRecord {`
- `  attempt_id: string                # task_id + attempt_index`
- `  task_id: string`
- `  backend_id: string`
- `  status: AdapterStatus`
- `  artifact_paths: list[string]`
- `  started_at: timestamp`
- `  finished_at: timestamp?`
- `  error: string?`
- `  is_partial: bool`
- `  resume_token: string?`
- `}`

Proposed change:
- add:
  - `attempt_index: integer`
  - `workspace_ref: string`
  - `winning_attempt: bool`
  - `blockers: list[string]`
  - `metadata: object?`

Why:
- These are required by the retry/isolation semantics already stated elsewhere.

### Edit 7 — define artifact manifest explicitly
Quote:
- `└── artifacts/        # Materialized artifact references`
- and
- `- ` + "`artifacts/`" + ` — manifest of all produced artifacts with content hashes`

Proposed change:
- In §26.1 change layout to:
  - `├── artifacts.json    # Artifact manifest with content hashes`
  - `└── artifacts/       # Materialized artifact payloads / refs`

Why:
- Current wording conflates directory and manifest.

### Edit 8 — define `RunSummary.terminal_status`
Quote:
- `terminal_status: enum`

Proposed change:
- `terminal_status: "complete" | "failed" | "blocked" | "partial" | "cancelled"`

Why:
- Right now the terminal vocabulary is unspecified.

### Edit 9 — add formal CLI/lint invocation surface
Quote:
- `The lint module MUST be importable and runnable without spinning up an Orchestrator. The skill-side LLM should call it before submitting to ` + "`crucible run`" + ` for fast feedback.`

Proposed change:
- Add: `Crucible exposes ` + "`crucible lint-plan <path|->`" + ` as the stable CLI entrypoint for preflight validation. The Python module remains importable for in-process callers.`

Why:
- The skill contract currently requires a local lint step, but no stable invocation surface exists.

### Edit 10 — define adapter state authority
Quote:
- `An event ingestor consumes push messages and updates the persisted adapter state`

Proposed change:
- Add: `Persisted adapter state under the owning run directory is the authoritative source for ` + "`poll()`" + ` and ` + "`collect()`" + ` after spawn. Router and CLI code MUST NOT depend on process-local listener state for correctness.`

Why:
- This closes the missed-push-event hole called out in the review.

---

## Final signoff

I would not mark v5.3 as NEEDS REVISION. The architecture is right and the addendum does a good job folding in the productionization review.

I would mark it READY WITH CLARIFICATIONS because:
- the overall direction is correct
- it fits the existing codebase as an additive Phase 8 layer
- the remaining issues are mostly contract precision, not architectural disagreement
- but there are a few important ambiguities that should be fixed before implementation starts, especially the status model, run/orchestrator mapping, and stable CLI intake/lint contracts

If those blocker clarifications are patched, the spec is ready to drive Phase 8 implementation.