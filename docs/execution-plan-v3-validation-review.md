# Execution Plan v3 Validation Review

## Core critique
The plan has the right components, but the current validation language is still too shallow to serve as a real signoff system. Most phase criteria are phrased as “verify X works” without defining:
- exact test shapes and fixture scenarios
- failure injection / negative-path coverage
- restart/resume / partial-state recovery checks
- evidence artifacts required for signoff
- independent reviewer attack questions
- hard fail conditions that block phase completion

Right now a builder could satisfy many checks with happy-path demos and lightweight unit tests. For v3, each phase should require a validation packet with must-pass gates, adversarial checks, and explicit evidence.

---

## Recommended reusable phase structure
Use the same structure in every phase section:

### 1. Build scope
- What code/assets may change in this phase
- What is explicitly out of scope
- Dependencies on earlier phases

### 2. Validation matrix
For each deliverable, include:
- requirement / contract
- positive-path test shape
- negative-path / failure injection test
- restart / resume test
- observability / evidence artifact
- pass threshold

### 3. Reviewer roles
For each phase, define:
- builder reviewer: checks implementation completeness
- adversarial reviewer: tries to break assumptions and induce false positives
- evidence reviewer: checks artifacts actually prove the claim

### 4. Must-pass gates
Examples:
- all critical tests green
- all required evidence artifacts attached
- reviewer verdict = pass with no unresolved blocking findings
- no open Sev1/Sev2 defects for phase scope
- restart/resume tests pass

### 5. Non-blocking observations
- design debt
- ergonomics concerns
- extension ideas
- non-critical performance issues

### 6. Fail-signoff conditions
Phase automatically fails signoff if any of these hold:
- only happy-path validation exists
- evidence is narrative rather than executable/artifact-backed
- restart/resume not tested where state exists
- reviewer found untested critical branch
- tests can still pass after removing the claimed implementation
- unresolved ambiguity in contract semantics

---

## Cross-phase validation rules to add once at top of plan
These should apply to every phase:

- Every phase ends with a **validation packet** stored in repo under `docs/validation/phase-N/`.
- Each packet must include:
  - validation matrix
  - executed test list
  - raw outputs / logs
  - failure injection results
  - restart/resume evidence
  - reviewer reports
  - signoff decision with blocker list
- No phase can sign off on builder assertion alone.
- Reviewer agent must read the ground-truth phase requirements, not builder summary.
- At least one reviewer per phase must explicitly try to falsify completion.
- “Works on sample” is not sufficient; require boundary cases and at least one hostile case.
- Signoff should be binary: `PASS`, `PASS WITH NON-BLOCKING OBSERVATIONS`, or `FAIL`.

---

## Phase-by-phase recommendations

## Phase 1 — Deterministic Substrate
### Missing rigor
Current checks are mostly structural. They do not prove state safety under malformed data, version drift, duplicate events, or restart recovery after mid-write failure.

### Add exact validation
- **State contracts**
  - roundtrip tests for minimal, typical, and maximal objects for all 6 state types
  - schema-rejection tests for missing required fields, extra unknown fields, wrong enum values, wrong version
  - migration/compatibility test for older serialized state if versioning exists
- **Ledger**
  - append sequence test with monotonic ordering and stable ids
  - duplicate event ingestion test
  - corrupted tail record test
  - simulated crash between write and fsync/commit boundary
  - concurrent append test from multiple writers if supported
- **Ambiguity gate**
  - fixture corpus of ambiguous prompts with expected output class + rationale
  - adversarial cases that look clear but hide missing acceptance criteria
  - false-positive test: clearly specified input must not be over-classified as ambiguous
- **Failure taxonomy**
  - table-driven tests mapping concrete failures to exact next action
  - unknown failure classification test must route to safe fallback, not silent success

### Required evidence artifacts
- serialized fixture set for all state types
- ledger append/read trace
- corrupted-ledger recovery log
- ambiguity-gate evaluation report on fixture corpus
- failure taxonomy decision table

### Hard signoff gates
- zero schema-acceptance bugs on invalid fixtures
- append-only invariant proven by test, not code inspection alone
- restart after interrupted ledger write either recovers safely or fails closed
- ambiguity gate accuracy on curated corpus meets threshold (define target, e.g. 100% on required fixture set)

### Adversarial reviewer checks
- Can I mutate state without a defined transition?
- Can I forge or overwrite prior ledger history?
- Can malformed state deserialize and silently proceed?
- Does ambiguity gate produce a plausible but unsafe `CLEAR` verdict?

---

## Phase 2 — Sub-Agent Management Cluster
### Missing rigor
The current phase does not validate race conditions, orphaned children, double-kill/idempotency, salvage correctness, or visibility staleness.

### Add exact validation
- **Run graph**
  - create parent + mixed child graph (blocking/non-blocking) and verify state transitions for success, failure, timeout, cancellation
  - orphan prevention test: parent exits unexpectedly, children must be reattached or cleaned up deterministically
- **Controller operations**
  - idempotency tests for `kill`, `collect`, `poll`
  - race test: child completes while parent cancellation is propagating
  - stale-status test: active-run visibility after rapid state changes
- **Partial/salvage behavior**
  - timeout after artifact creation but before completion flag
  - salvage worker resumes from exact known checkpoint, not redoes blind
  - salvage worker blocked if evidence/artifacts insufficient
- **Circuit breaker**
  - repeated same-error with slightly different wording should still trip
  - different root causes should not collapse into one bucket and trip incorrectly

### Required evidence artifacts
- run lifecycle traces for all terminal states
- cancellation propagation logs
- salvage replay transcript showing resumed vs skipped work
- circuit-breaker threshold test output
- active-run snapshot before/after concurrent transitions

### Hard signoff gates
- no orphaned runs after forced parent termination test
- `kill` and `collect` are idempotent under repeated invocation
- partial outcome preserved with artifacts intact after timeout
- salvage path demonstrates true recovery on interrupted run

### Adversarial reviewer checks
- Can a run disappear from active view while still consuming resources?
- Can cancellation kill the wrong child set?
- Does salvage invent completion without proving resumed work?
- Can loop detection be bypassed by message variation?

---

## Phase 3 — Validation and Review Foundation
### Missing rigor
This phase is the most under-specified relative to its importance. “Validation ladder executes in order” is not enough; this phase must prove that validation can catch missing implementation, shallow tests, and fake evidence.

### Add exact validation
- **Validation ladder**
  - force failure independently at each rung and prove later rungs do not mask the failure
  - prove rung outputs are attached to criteria, not just emitted globally
- **Verification triple**
  - require canonical template with explicit acceptance criteria, exact commands, expected observable outputs, and failure signatures
  - invalid/incomplete triple must block task start or signoff
- **Evidence mapping**
  - each spec criterion must map to at least one artifact and one executable check
  - detect orphan evidence (artifact with no criterion) and orphan criterion (criterion with no evidence)
- **Anti-vacuity**
  - remove/disable claimed implementation and ensure validation packet fails
  - substitute stub/mock implementation and ensure reviewer detects insufficiency
- **Reviewer workflow**
  - reviewer must produce: covered criteria, untested branches, possible false positives, escaped defect hypotheses, blocking verdict

### Required evidence artifacts
- validation ladder execution transcript with per-rung status
- criterion→evidence map
- anti-vacuity test output
- reviewer report using fixed schema
- blocked-signoff example showing must-pass gate enforcement

### Hard signoff gates
- no criterion may be signed off without executable evidence
- anti-vacuity challenge must fail when implementation removed/stubbed
- reviewer identifies zero unaddressed critical untested paths
- must-pass gate failure leaves task/build in incomplete state in persisted state model

### Adversarial reviewer checks
- If I delete the core implementation, what still passes?
- Are tests asserting behavior or just execution/no-crash?
- Is evidence tied to requirements or just attached nearby?
- Can a reviewer output “pass” without discussing escaped-defect risk?

---

## Phase 4 — Scheduling and Memory Foundation
### Missing rigor
The current phase lacks measurable thresholds and resilience checks under pressure. “Scheduler respects limits” is too vague.

### Add exact validation
- **Machine profile**
  - compare detected profile against system commands with tolerance bounds
  - missing metric fallback behavior test
- **Intensity classification**
  - fixture suite of tasks with expected classifications
  - adversarial examples that look light but imply heavy downstream work
- **Scheduler**
  - load tests with mixed light/medium/heavy tasks
  - verify concurrency decisions over time, not just end state
  - forced low-memory / high-CPU simulation to check throttling and backoff
  - starvation/fairness test so light tasks do not block forever behind heavy queue
- **Memory/lessons**
  - persist lesson, restart, retrieve, inject into spawned run
  - stale/contradictory lesson test
  - memory isolation test to ensure host conversational memory is never injected as harness memory

### Required evidence artifacts
- machine-profile diff report
- scheduler decision timeline under stress
- resource-utilization logs during stress run
- persisted lesson file + retrieval proof after restart
- injected-memory transcript showing exact memory payload

### Hard signoff gates
- scheduler maintains defined resource headroom thresholds under stress
- no cross-contamination between harness memory and host memory
- persisted lessons survive restart and are consulted on retry path
- classification accuracy meets threshold on fixture set

### Adversarial reviewer checks
- Can scheduler thrash under oscillating load?
- Can heavy tasks starve all other work?
- Can stale lesson override newer truth?
- Can host-private memory leak into harness task context?

---

## Phase 5 — Unified Project Workflows
### Missing rigor
This phase currently validates broad outcomes but not recovery, rollback, or quality of generated project state. It also needs stronger real-repo acceptance criteria.

### Add exact validation
- **Existing-project intake**
  - run against at least 3 repo archetypes: clean modern repo, messy legacy repo, partially broken repo
  - verify mis-detection behavior is surfaced, not silently guessed
- **Worktree isolation**
  - concurrent builders modify overlapping files in separate worktrees
  - verify no bleed into main checkout and collisions are surfaced cleanly
- **Greenfield bootstrap**
  - bootstrap each supported project type from empty directory
  - run install, local start/build, tests, and CI from generated scaffold
  - inject failure: missing credentials, network failure, partial GitHub repo creation, CI config syntax bug
- **First-working-version gate**
  - require proof artifact from actual running project, not just build success
  - recovery test from interrupted bootstrap midway through scaffold/repo/CI setup
  - rerun on partially initialized repo must be safe/idempotent or explicitly fail with repair guidance

### Required evidence artifacts
- intake reports for each archetype repo
- worktree isolation diff traces
- generated scaffold tree + run logs + CI run URLs
- interrupted-bootstrap recovery transcript
- first-working-version proof artifacts (screenshot, curl response, CLI output)

### Hard signoff gates
- every supported bootstrap type demonstrated end-to-end on real scaffold
- at least one interrupted bootstrap successfully resumed or safely repaired
- GitHub/CI failure modes degrade cleanly without corrupting local state
- first-working-version gate requires executable proof, not scaffolding presence alone

### Adversarial reviewer checks
- Can intake hallucinate framework/test setup on ambiguous repo structure?
- Can parallel worktrees accidentally share mutable state?
- Can bootstrap leave a half-created repo that later paths misread as healthy?
- Is “working version” actually runnable by a fresh clone?

---

## Phase 6 — Optional Accelerators
### Missing rigor
Even though optional, abstraction layers often create hidden semantic mismatch. Need compatibility and fallback correctness, not just method presence.

### Add exact validation
- capability matrix test for each backend against interface claims
- semantic parity test: same RunSpec on different backends produces equivalent lifecycle semantics
- fallback test where preferred backend fails mid-run, not only before spawn
- unsupported-capability test must fail explicitly, not degrade silently

### Required evidence artifacts
- backend capability matrix
- parity test report across backends
- fallback/failover trace
- unsupported-capability rejection examples

### Hard signoff gates
- backend capability declarations match observed behavior
- routing decisions are explainable and logged
- fallback preserves run accounting and evidence chain

### Adversarial reviewer checks
- Does a backend claim support it does not really have?
- Can failover duplicate work or lose artifacts?
- Do different backends produce inconsistent terminal states?

---

## Recommended independent reviewer agents
These should exist across phases, with strict context isolation from builders:

### 1. Contract reviewer
Checks:
- state/schema/interface completeness
- invariants and transition legality
- backward/forward compatibility assumptions

### 2. Adversarial validator
Checks:
- negative paths
- malformed input handling
- false-positive completion
- anti-vacuity / stub-pass attempts

### 3. Recovery reviewer
Checks:
- restart/resume behavior
- partial-state handling
- interrupted write / timeout / crash recovery
- idempotent rerun behavior

### 4. Evidence reviewer
Checks:
- each claim has concrete artifact(s)
- artifacts map to criteria
- logs are raw enough to audit
- screenshots/demos are not the sole proof for logic claims

### 5. Systems reviewer
Checks:
- concurrency/resource behavior
- scheduler fairness/headroom
- race conditions / stale visibility / orphan processes

### 6. End-to-end reviewer
Checks:
- full workflow from user input to proof artifact
- fresh-environment reproducibility
- actual usability, not just component correctness

Recommendation: require at least 2 independent reviewers per phase:
- one domain reviewer for the phase
- one adversarial/evidence reviewer

For Phase 3 and Phase 5, require 3 reviewers because they define global trustworthiness and end-to-end usefulness.

---

## Specific edits to make in EXECUTION_PLAN.md
1. Replace each current “Validation Criteria” table with a richer **Validation Matrix** containing:
   - requirement
   - positive test
   - negative/failure injection test
   - restart/resume test
   - required evidence
   - blocking gate
2. Add a **Signoff Packet** subsection to every phase with required files/artifacts.
3. Add a **Fail-Signoff Conditions** subsection to every phase.
4. Add an **Adversarial Review Questions** subsection to every phase.
5. Add explicit quantitative thresholds where possible:
   - fixture corpus size
   - zero tolerance for critical invalid acceptance
   - resource headroom targets
   - required number of real repo/workflow demos
6. Upgrade reviewer sections from one reviewer to named independent reviewer types with explicit responsibilities.
7. Make restart/resume/failure-injection mandatory anywhere state, orchestration, scheduling, or external side effects exist.
8. In Phase 3, make anti-vacuity a mandatory blocking gate for the whole project, not just that phase.

---

## Highest-impact edits to make first
1. **Rewrite Phase 3 validation into a real signoff system**: criterion→evidence mapping, anti-vacuity, blocking gates, fixed reviewer output schema.
2. **Replace all phase validation tables with full validation matrices** including failure injection, restart/resume, required evidence, and hard fail conditions.
3. **Require per-phase validation packets under `docs/validation/phase-N/`** so signoff is artifact-backed and auditable.
4. **Add adversarial + recovery reviewers across phases** rather than one generic reviewer per phase.
5. **Strengthen Phase 2 and Phase 5 with interruption/recovery/idempotency tests** since orchestration and bootstrap are where shallow validation will most likely hide real failures.
