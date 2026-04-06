# Agentic Harness v5.2 — Execution Plan v3

**Status:** In Progress  
**Date:** 2026-04-06  
**Ground Truth:** PRD v5.2 + Technical Design v5.2  
**Repository:** `~/Projects/agentic-harness-v5.2/`

---

## Overview

This execution plan breaks the Agentic Harness v5.2 implementation into 6 phases with explicit build scope, validation matrices, reviewer roles, signoff packets, and fail conditions.

The key shift in v3 is this:
- a phase is not done because the builder says it works
- a phase is done only when a **validation packet** proves it
- every phase includes positive-path tests, negative-path tests, restart/recovery tests where relevant, and independent review

---

## Cross-Phase Signoff Rules

These rules apply to every phase.

### Validation packet requirement
Every phase must end with a validation packet stored under:
- `docs/validation/phase-1/`
- `docs/validation/phase-2/`
- `docs/validation/phase-3/`
- `docs/validation/phase-4/`
- `docs/validation/phase-5/`
- `docs/validation/phase-6/`

Each packet must include:
- validation matrix
- executed test list
- raw logs / command outputs
- failure injection results
- restart / resume results where state exists
- reviewer reports
- final signoff decision
- blocker list if not fully passing

### Allowed signoff outcomes
- `PASS`
- `PASS WITH NON-BLOCKING OBSERVATIONS`
- `FAIL`

### Global must-pass rules
- No phase signs off on builder assertion alone
- At least one reviewer per phase must explicitly try to falsify completion
- “Works on sample input” is never enough by itself
- If state exists, restart/resume must be tested
- If external side effects exist, idempotency or safe-failure behavior must be tested
- If a core claim can be removed while tests still pass, signoff fails

### Common reviewer roles
Use these reviewer types across phases as needed:
- **Contract Reviewer** — checks schemas, interfaces, invariants, state legality
- **Adversarial Reviewer** — attacks negative paths, fake passes, malformed input, shallow validation
- **Recovery Reviewer** — attacks restart/resume, interrupted state, idempotency, salvage correctness
- **Evidence Reviewer** — checks whether artifacts actually prove the claim
- **Systems Reviewer** — checks concurrency, resources, race conditions, stale visibility
- **End-to-End Reviewer** — checks whole workflow from user input to proof artifact

Minimum reviewer rule:
- Every phase needs at least 2 independent reviewers:
  - one domain reviewer for the phase
  - one adversarial or evidence reviewer
- Phases 3 and 5 need at least 3 reviewers because they define trustworthiness and end-to-end usefulness

---

## Phase 1: Deterministic Substrate

### Goal
Establish the core state contracts, append-only ledger, ambiguity gate, and failure taxonomy.

### Build scope
In scope:
- `ProjectState`, `BuildState`, `TaskState`, `RunState`, `ValidationState`, `IntegrationState`
- append-only ledger and event schema
- ambiguity gate outputs
- failure taxonomy and classification behavior

Out of scope:
- real sub-agent execution
- workflow automation
- scheduler behavior

Dependencies:
- none

### Deliverables
- state schemas and serializers
- ledger implementation
- ambiguity classifier
- failure classifier
- seed fixtures for state and ambiguity testing

### Validation matrix

#### State contracts
- Positive test:
  - roundtrip serialize/deserialize minimal, normal, and maximal examples for all 6 state types
- Negative test:
  - reject missing required fields, wrong enums, malformed nested objects, unknown critical keys if schema is strict
- Restart/recovery test:
  - persist state, reload after process restart, verify exact equivalence
- Required evidence:
  - fixture set, schema validation outputs, roundtrip logs
- Blocking gate:
  - zero invalid fixtures accepted silently

#### Ledger
- Positive test:
  - append sequence of events and verify stable order, ids, and re-read consistency
- Negative test:
  - duplicate event ingestion, corrupted tail record, malformed event payload
- Restart/recovery test:
  - simulate interrupted write and verify recovery or safe fail-closed behavior
- Required evidence:
  - append trace, corrupted-ledger recovery log, invariant test output
- Blocking gate:
  - append-only invariant proven by test, not inspection alone

#### Ambiguity gate
- Positive test:
  - curated fixture corpus produces correct `CLEAR`, `CLARIFY`, `SPLIT`, `DEFER` outputs
- Negative test:
  - adversarial prompts that look clear but hide missing acceptance criteria
- Restart/recovery test:
  - deterministic re-run on same fixture corpus yields stable output format
- Required evidence:
  - fixture corpus, expected labels, actual labels, mismatch report
- Blocking gate:
  - no critical false `CLEAR` on required corpus

#### Failure taxonomy
- Positive test:
  - table-driven cases map concrete failures to expected next actions
- Negative test:
  - unknown failure kinds route to safe fallback instead of silent success
- Restart/recovery test:
  - classification persists correctly in stored task/build state
- Required evidence:
  - decision table, test transcript
- Blocking gate:
  - every supported failure class has one deterministic next action

### Required signoff packet
- `docs/validation/phase-1/validation-matrix.md`
- `docs/validation/phase-1/state-fixtures/`
- `docs/validation/phase-1/ledger-tests.log`
- `docs/validation/phase-1/ambiguity-corpus-report.md`
- `docs/validation/phase-1/failure-taxonomy-report.md`
- reviewer reports
- final signoff file

### Reviewer roles
- Contract Reviewer
- Adversarial Reviewer
- Evidence Reviewer

### Must-pass gates
- all 6 state types pass roundtrip + invalid-fixture rejection tests
- ledger append-only invariant proven under malformed/corrupted input tests
- interrupted ledger write recovers safely or fails closed
- ambiguity corpus passes required threshold with zero critical unsafe clears
- failure taxonomy maps every supported failure class to deterministic next action

### Non-blocking observations
- ergonomics of schema definitions
- naming clarity
- future migration/versioning improvements

### Fail-signoff conditions
- malformed state can silently deserialize into valid execution path
- ledger history can be mutated or overwritten
- ambiguity gate produces unsafe `CLEAR` on critical corpus cases
- evidence is narrative only, with no raw logs or fixtures

### Adversarial review questions
- Can I mutate state without a defined transition?
- Can I forge or overwrite ledger history?
- Can malformed state silently proceed?
- Can ambiguity be misclassified as safe to build?

---

## Phase 2: Sub-Agent Management Cluster

### Goal
Build the run graph, role templates, controller operations, salvage paths, and active-run visibility.

### Build scope
In scope:
- run graph model
- parent/child semantics
- controller operations: spawn, poll, collect, kill
- timeout salvage
- rejection ledger + circuit breaker
- active-run visibility

Out of scope:
- end-to-end repo workflows
- CI/bootstrap logic

Dependencies:
- Phase 1 complete

### Deliverables
- run graph state model
- role templates
- controller implementation
- salvage/resume logic
- active-run view
- circuit breaker + rejection ledger

### Validation matrix

#### Run graph semantics
- Positive test:
  - parent with mixed blocking/non-blocking children across success, failure, timeout, cancellation
- Negative test:
  - orphan-child scenario after unexpected parent termination
- Restart/recovery test:
  - reload persisted run graph mid-execution and continue correctly
- Required evidence:
  - lifecycle trace logs, run graph snapshots
- Blocking gate:
  - no orphaned runs after forced parent termination scenarios

#### Controller operations
- Positive test:
  - spawn/poll/collect/kill across normal lifecycle
- Negative test:
  - repeated `kill`, repeated `collect`, poll during terminal transition, race between completion and cancellation
- Restart/recovery test:
  - restart controller while runs are in mixed states and rehydrate correctly
- Required evidence:
  - idempotency logs, race test logs
- Blocking gate:
  - `kill` and `collect` are idempotent

#### Salvage behavior
- Positive test:
  - timeout after artifacts exist; salvage resumes from exact checkpoint
- Negative test:
  - salvage blocked when artifacts/checkpoint are insufficient
- Restart/recovery test:
  - salvage after controller restart still resumes correctly
- Required evidence:
  - salvage replay transcript, before/after artifacts
- Blocking gate:
  - partial outcomes preserved with artifacts intact

#### Circuit breaker
- Positive test:
  - repeated same failure triggers breaker at threshold
- Negative test:
  - slightly varied wording still counted as same failure when root cause is same; distinct failures do not trip incorrectly
- Restart/recovery test:
  - breaker state persists across restart
- Required evidence:
  - rejection ledger trace, breaker threshold transcript
- Blocking gate:
  - loop detection works on semantically repeated failure, not string match only

#### Active-run visibility
- Positive test:
  - view reflects all active runs, status, role, blocked reason
- Negative test:
  - stale snapshot during rapid transitions
- Restart/recovery test:
  - visibility rebuilt after restart without ghost or missing runs
- Required evidence:
  - before/after snapshots, transition timeline
- Blocking gate:
  - no hidden active runs and no ghost completed runs

### Required signoff packet
- `docs/validation/phase-2/validation-matrix.md`
- run lifecycle traces
- cancellation/race logs
- salvage transcripts
- circuit-breaker report
- active-run visibility report
- reviewer reports
- final signoff file

### Reviewer roles
- Contract Reviewer
- Recovery Reviewer
- Adversarial Reviewer
- Systems Reviewer

### Must-pass gates
- no orphaned runs after forced parent termination test
- controller operations are idempotent under repeated invocation
- salvage demonstrates true recovery, not blind re-execution
- circuit breaker trips on true loops and avoids obvious false positives
- active-run view stays correct through rapid transitions and restart

### Non-blocking observations
- visibility UX polish
- future role taxonomy expansion
- better tracing formats

### Fail-signoff conditions
- a run can disappear while still consuming resources
- cancellation kills the wrong child set
- salvage fabricates completion without preserved artifacts
- active-run view is stale enough to mislead orchestration

### Adversarial review questions
- Can a run vanish from active view while still alive?
- Can cancellation propagate incorrectly?
- Can salvage “complete” a task without proving resumed work?
- Can loops bypass detection by superficial variation?

---

## Phase 3: Validation and Review Foundation

### Goal
Create the global signoff system: validation ladder, verification triples, criterion→evidence mapping, anti-vacuity checks, and completion semantics.

### Why Phase 3 is special
This phase is the backbone of trust for the whole project. If this phase is weak, every later phase can look complete while still being shallow or fake.

### Build scope
In scope:
- validation ladder
- verification triple templates and enforcement
- evidence mapping
- reviewer output schemas
- anti-vacuity logic
- completion semantics

Out of scope:
- full workflow automation itself
- backend accelerators

Dependencies:
- Phases 1 and 2 complete

### Deliverables
- validation ladder executor
- verification triple schema/template
- criterion→evidence mapping model
- reviewer schema
- anti-vacuity checks
- task/build completion logic

### Validation matrix

#### Validation ladder
- Positive test:
  - run all rungs in order with passing implementation
- Negative test:
  - force failure independently at each rung and prove later rungs do not mask failure
- Restart/recovery test:
  - resume validation from partial rung completion after interruption
- Required evidence:
  - rung-by-rung transcript, per-rung outputs
- Blocking gate:
  - must-pass rung failure always blocks completion state

#### Verification triple
- Positive test:
  - valid triples specify build target, exact verification commands, expected outputs, failure signatures
- Negative test:
  - incomplete/ambiguous triples rejected before task signoff or start
- Restart/recovery test:
  - triples persist and remain linked after restart
- Required evidence:
  - canonical triple examples, rejection tests
- Blocking gate:
  - task cannot sign off without complete triple

#### Criterion→evidence mapping
- Positive test:
  - every criterion linked to at least one executable check and one artifact
- Negative test:
  - detect orphan criteria and orphan evidence
- Restart/recovery test:
  - evidence links survive persistence and reload
- Required evidence:
  - mapping report, orphan detection report
- Blocking gate:
  - no signed-off criterion without executable evidence

#### Anti-vacuity
- Positive test:
  - real implementation passes
- Negative test:
  - remove or stub implementation and prove validation packet fails
- Restart/recovery test:
  - anti-vacuity challenge reruns after interruption without losing verdict integrity
- Required evidence:
  - anti-vacuity report, removed-implementation test logs
- Blocking gate:
  - anti-vacuity challenge must fail when implementation is removed or stubbed

#### Reviewer workflow
- Positive test:
  - reviewer outputs fixed schema: covered criteria, untested branches, escaped-defect risks, verdict
- Negative test:
  - reviewer attempts to pass without discussing missing evidence or untested critical branch
- Restart/recovery test:
  - reviewer outputs persist and attach correctly to task/build state
- Required evidence:
  - reviewer schema examples, blocked-signoff examples
- Blocking gate:
  - reviewer cannot mark pass while leaving unresolved critical branch unaddressed

### Required signoff packet
- `docs/validation/phase-3/validation-matrix.md`
- validation ladder transcript
- criterion-evidence map
- anti-vacuity report
- reviewer schema examples
- blocked-signoff example
- reviewer reports
- final signoff file

### Reviewer roles
- Evidence Reviewer
- Adversarial Reviewer
- Contract Reviewer

### Must-pass gates
- every criterion has executable evidence
- anti-vacuity challenge fails when implementation removed/stubbed
- must-pass gate failure persists incomplete state correctly
- reviewer outputs follow strict schema and surface untested critical branches
- no task/build can be marked complete on narrative evidence alone

### Non-blocking observations
- report formatting quality
- additional reviewer heuristics
- future richer scoring models

### Fail-signoff conditions
- happy-path tests only
- evidence attached near criteria but not actually linked
- implementation can be removed while tests still pass
- reviewer can approve without discussing escaped-defect risk
- must-pass gate fails but state still marks task complete

### Adversarial review questions
- If I delete the core implementation, what still passes?
- Are tests checking behavior or just non-crash?
- Is evidence tied to requirements or merely nearby?
- Can reviewer output “pass” without real critique?

---

## Phase 4: Scheduling and Memory Foundation

### Goal
Build machine-aware scheduling, harness-owned memory, and persistence rules that survive real pressure and restart.

### Build scope
In scope:
- machine profile
- intensity classification
- adaptive concurrency heuristics
- harness memory retrieval/injection
- lesson persistence and reuse

Out of scope:
- full end-to-end bootstrap workflows

Dependencies:
- Phase 3 complete

### Deliverables
- machine profile detector
- task intensity classifier
- scheduler heuristics
- memory store/retrieval layer
- lesson persistence and injection logic

### Validation matrix

#### Machine profile
- Positive test:
  - profile matches system commands within tolerance
- Negative test:
  - missing/unavailable metric handled safely
- Restart/recovery test:
  - profile reload after restart
- Required evidence:
  - machine-profile diff report
- Blocking gate:
  - detected profile consistent with actual host within defined tolerance

#### Intensity classification
- Positive test:
  - fixture suite of tasks classified correctly
- Negative test:
  - adversarial “looks-light-but-is-heavy” cases detected
- Restart/recovery test:
  - persisted classification remains stable after reload
- Required evidence:
  - fixture corpus, classification report
- Blocking gate:
  - classification accuracy meets threshold on fixture set

#### Scheduler
- Positive test:
  - mixed light/medium/heavy tasks scheduled while preserving headroom
- Negative test:
  - forced low-memory, high-CPU, and oscillating-load scenarios
- Restart/recovery test:
  - scheduler recovers queued/running task state after restart
- Required evidence:
  - decision timeline, resource-utilization logs, stress-test report
- Blocking gate:
  - scheduler preserves defined CPU/memory headroom under stress

#### Memory and lessons
- Positive test:
  - persist lesson, restart, retrieve, inject into run
- Negative test:
  - stale/contradictory lesson, memory contamination attempt from host conversation context
- Restart/recovery test:
  - lesson survives restart and is consulted during retry path
- Required evidence:
  - persisted lesson file, retrieval proof, injection transcript
- Blocking gate:
  - no host-memory leakage into harness-owned memory

### Required signoff packet
- `docs/validation/phase-4/validation-matrix.md`
- machine-profile report
- scheduler stress logs
- resource timeline charts/logs
- lesson persistence report
- memory injection transcript
- reviewer reports
- final signoff file

### Reviewer roles
- Systems Reviewer
- Recovery Reviewer
- Evidence Reviewer

### Must-pass gates
- scheduler maintains target resource headroom under stress
- restart/recovery preserves queue/scheduling correctness
- lessons survive restart and influence retry path correctly
- no cross-contamination between host memory and harness memory
- classification threshold met on curated fixture set

### Non-blocking observations
- tuning improvements
- future richer classification model
- dashboard ergonomics

### Fail-signoff conditions
- scheduler thrashes under oscillating load
- heavy tasks starve all other work
- stale lesson overrides newer truth without conflict handling
- host-private memory leaks into harness context

### Adversarial review questions
- Can scheduler thrash under unstable load?
- Can heavy tasks starve light ones forever?
- Can stale lessons override newer truth?
- Can host memory leak into harness memory?

---

## Phase 5: Unified Project Workflows

### Goal
Implement existing-project intake and greenfield bootstrap on top of the earlier validation and scheduling foundations.

### Build scope
In scope:
- existing-project inspection
- branch/worktree isolation
- greenfield bootstrap
- GitHub repo creation
- CI baseline creation
- first-working-version gate
- Python as default backend language
- `uv` as default Python package/project manager

Out of scope:
- optional accelerator adapters

Dependencies:
- Phases 1–4 complete

### Deliverables
- existing-repo intake logic
- worktree management
- greenfield scaffold logic
- GitHub/CI setup flow
- first-working-version gate
- bootstrap defaults matrix

### Validation matrix

#### Existing-project intake
- Positive test:
  - run against at least 3 repo archetypes: clean modern repo, messy legacy repo, partially broken repo
- Negative test:
  - ambiguous repo structure should surface uncertainty instead of hallucinating framework/test setup
- Restart/recovery test:
  - interrupted intake can safely resume or fail with explicit repair guidance
- Required evidence:
  - intake reports for all archetypes
- Blocking gate:
  - no silent hallucinated repo classification on adversarial fixtures

#### Worktree isolation
- Positive test:
  - concurrent builders modify overlapping files in separate worktrees without bleed into main checkout
- Negative test:
  - induced overlap/conflict surfaces cleanly
- Restart/recovery test:
  - worktree state remains consistent after interrupted operation/restart
- Required evidence:
  - worktree diff traces, conflict report
- Blocking gate:
  - no mutation bleed into main checkout during parallel worktree tests

#### Greenfield bootstrap
- Positive test:
  - bootstrap each supported project type from empty directory and run install, tests, local start/build, CI
- Negative test:
  - missing credentials, network failure, partial GitHub repo creation, CI syntax bug
- Restart/recovery test:
  - interrupted bootstrap resumes safely or fails with explicit repair guidance
- Required evidence:
  - scaffold trees, run logs, CI outputs, recovery transcript
- Blocking gate:
  - every supported bootstrap type demonstrated end-to-end

#### First-working-version gate
- Positive test:
  - proof artifact from actual running project (screenshot, curl response, CLI output)
- Negative test:
  - scaffolding present but project not runnable/buildable should fail
- Restart/recovery test:
  - rerun on partially initialized repo is idempotent or safely repairable
- Required evidence:
  - fresh-run proof artifacts, rerun transcript
- Blocking gate:
  - first-working-version requires executable proof, not scaffold presence alone

### Required signoff packet
- `docs/validation/phase-5/validation-matrix.md`
- intake reports
- worktree isolation traces
- scaffold trees and run logs
- CI outputs/links
- interrupted-bootstrap recovery transcript
- first-working-version proof artifacts
- reviewer reports
- final signoff file

### Reviewer roles
- End-to-End Reviewer
- Adversarial Reviewer
- Recovery Reviewer
- Evidence Reviewer

### Must-pass gates
- all supported bootstrap types pass real end-to-end demo from empty directory
- at least one interrupted bootstrap successfully resumes or safely repairs
- GitHub/CI failure modes degrade cleanly without corrupting local state
- first-working-version gate requires runnable proof artifact
- Python is default backend choice unless spec overrides it
- `uv` is default Python package/project manager unless spec overrides it

### Non-blocking observations
- scaffold ergonomics
- optional alternative stacks
- nicer repo summaries

### Fail-signoff conditions
- intake hallucinates repo structure on ambiguity
- parallel worktrees share mutable state accidentally
- half-created repos are later treated as healthy
- fresh clone cannot run what is called a “working version”

### Adversarial review questions
- Can intake hallucinate framework/test setup?
- Can worktrees bleed into each other or main checkout?
- Can bootstrap leave toxic half-state behind?
- Is “working version” actually runnable by a fresh clone?

---

## Phase 6: Optional Accelerators

### Goal
Add optional backend adapters without breaking semantics, evidence chains, or fallback safety.

### Build scope
In scope:
- backend capability routing
- Claude Code adapter
- Codex adapter
- semantic parity across backends

Out of scope:
- making accelerators mandatory for core function

Dependencies:
- Phases 1–5 complete

### Deliverables
- backend capability matrix
- adapter implementations
- routing logic
- fallback behavior

### Validation matrix

#### Backend capability declarations
- Positive test:
  - observed behavior matches declared capabilities
- Negative test:
  - backend claims unsupported feature
- Restart/recovery test:
  - capability state/routing survives restart
- Required evidence:
  - capability matrix report
- Blocking gate:
  - no backend capability mismatch on required features

#### Semantic parity
- Positive test:
  - same RunSpec across backends yields equivalent lifecycle semantics
- Negative test:
  - terminal states diverge or evidence chains differ materially
- Restart/recovery test:
  - failover during or after interruption preserves run accounting
- Required evidence:
  - parity report, lifecycle traces
- Blocking gate:
  - routing preserves lifecycle semantics and evidence chain

#### Fallback behavior
- Positive test:
  - preferred backend unavailable before spawn → fallback works
- Negative test:
  - preferred backend fails mid-run; fallback preserves accounting and artifacts
- Restart/recovery test:
  - failover after restart/reload still behaves deterministically
- Required evidence:
  - failover trace, rejection examples
- Blocking gate:
  - fallback never loses artifacts or duplicates work silently

### Required signoff packet
- `docs/validation/phase-6/validation-matrix.md`
- capability matrix
- parity report
- failover traces
- unsupported-capability rejection examples
- reviewer reports
- final signoff file

### Reviewer roles
- Contract Reviewer
- Adversarial Reviewer
- Evidence Reviewer

### Must-pass gates
- capability declarations match observed behavior
- routing decisions are explainable and logged
- fallback preserves run accounting and evidence chain
- unsupported capability fails explicitly, not silently

### Non-blocking observations
- adapter ergonomics
- richer routing heuristics
- future backend additions

### Fail-signoff conditions
- backend claims support it does not actually have
- failover duplicates work or loses artifacts
- different backends produce inconsistent terminal state semantics

### Adversarial review questions
- Does a backend overclaim capabilities?
- Can failover lose or duplicate work?
- Do lifecycle semantics drift across backends?
- Are routing decisions opaque or unverifiable?

---

## Phase Timeline

- **Phase 1** — deterministic substrate
- **Phase 2** — sub-agent management cluster
- **Phase 3** — validation and review foundation
- **Phase 4** — scheduling and memory foundation
- **Phase 5** — unified project workflows
- **Phase 6** — optional accelerators

---

## Repository Structure

```
agentic-harness-v5.2/
├── README.md
├── EXECUTION_PLAN.md
├── docs/
│   ├── agentic-harness-spec-v5.2.md
│   ├── agentic-harness-prd-v5.2.md
│   ├── agentic-harness-technical-design-v5.2.md
│   └── validation/
│       ├── phase-1/
│       ├── phase-2/
│       ├── phase-3/
│       ├── phase-4/
│       ├── phase-5/
│       └── phase-6/
├── src/
└── tests/
```

---

## Summary

v3 strengthens the plan in four major ways:
- every phase now has a validation matrix instead of a shallow checklist
- every phase now requires a signoff packet with raw evidence
- adversarial and recovery review are mandatory, not optional
- completion is defined by blocking gates and fail-signoff conditions, not by narrative confidence
