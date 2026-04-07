# Adversarial Review — Phase 3 Validation and Review Foundation

Verdict: FAIL

## Findings (blocking) with concrete evidence

### 1) Validation can pass on unverifiable string evidence, with no artifact linkage or executable proof
- Spec requires validation to be tied back to the spec and to prefer executable proof over narrative confidence (`docs/agentic-harness-spec-v5.2.md:570-578`).
- Execution plan requires every criterion to link to at least one executable check and one artifact, with no signed-off criterion without executable evidence (`EXECUTION_PLAN.md:382-392`, `433-438`).
- Implementation `Evidence` is only:
  - `type: str`
  - `content: str`
  - `source: str`
  - `timestamp: float`
  (`src/agentic_harness/validation/validation.py:42-48`)
- There is no artifact ref, no path, no hash, no command, no reachability check, no existence check, no immutability check, and no linkage to the artifact model required by spec (`agentic-harness-spec-v5.2.md:549-564`).
- `_judge()` returns `PASS` for any non-vacuous evidence string, regardless of whether it is real, reachable, executable, or corresponds to the criterion (`validation.py:135-140`).

Attack example:
- Evidence content: `"All 85 tests passed with no failures"`
- Source: `"pytest"`
- No artifact, no command output, no file, no CI run, no log ref
- Current implementation treats this as non-vacuous and therefore `PASS`.

Impact:
- Phase 3’s core promise fails: narrative evidence alone can produce passing validation.

### 2) Completion can be marked complete even when required criteria are BLOCKED
- Spec says a task may be complete only when all must-pass gates have passed or are explicitly unavailable for legitimate reasons (`agentic-harness-spec-v5.2.md:612-617`).
- Execution plan says must-pass rung failure always blocks completion state, and must-pass gate failure must persist incomplete state correctly (`EXECUTION_PLAN.md:358-368`, `433-438`).
- Implementation sets `result.is_complete = not result.required_fail_count` (`validation.py:120`).
- `required_fail_count` counts only `FAIL`, not `BLOCKED` (`validation.py:77-81`).
- Therefore a result with zero `FAIL` and all criteria `BLOCKED` is marked complete.

Concrete failure mode:
- Run `execute(..., VerificationLevel.VERIFY)` with required criteria and no evidence.
- `_judge()` returns `BLOCKED` (`validation.py:130-133`).
- `required_fail_count == 0` so `is_complete == True` (`validation.py:120`).

Impact:
- Missing evidence can still yield a complete validation result.
- This directly violates the spec and execution plan.

### 3) Verdict precedence is wrong: completion is driven by pass-rate heuristics instead of gate semantics
- Spec defines completion by required deliverables, must-pass gates, informational gaps, and review resolution — not by percentage pass rate (`agentic-harness-spec-v5.2.md:612-622`).
- Implementation `TaskCompletion.determine()` ignores requiredness, gate classes, blocked state, deliverables, and review findings. It uses:
  - `>= 0.8` pass rate → `complete`
  - `>= 0.4` pass rate → `partial`
  - else `failed`
  (`validation.py:177-196`)
- This allows contradictory outcomes:
  - a single blocking gate could fail, yet enough other checks could produce `complete`
  - a result with blocked must-pass evidence could still score as `partial` or even `complete`

Impact:
- Must-pass vs informational semantics from spec §12.3 are not modeled at all.
- Gate precedence is not enforced.

### 4) Acceptance criteria, gates, and verification triples are not modeled per spec/plan
- Spec requires each task to declare what to build, how to verify it, and what failure looks like (`agentic-harness-spec-v5.2.md:263-267`), and Phase 3 deliverables include verification triple schema/template and criterion→evidence mapping (`EXECUTION_PLAN.md:350-353`).
- Implementation `VerificationTriple` contains only:
  - `criterion_id`
  - `evidence`
  - `verdict`
  - `notes`
  (`validation.py:51-57`)
- It does not encode:
  - build target
  - exact verification commands
  - expected outputs
  - failure signatures
  - must-pass vs informational status
  - artifact refs
- Execution plan explicitly requires these (`EXECUTION_PLAN.md:370-380`).

Impact:
- The foundational data model is missing the fields needed to represent the required contract.
- “Triple” here is not the triple Phase 3 actually needs.

### 5) Evidence linkage is not durable across persistence/restart because persistence is not implemented
- Execution plan requires restart/recovery tests for ladder execution, triples, criterion→evidence mapping, anti-vacuity, and reviewer outputs (`EXECUTION_PLAN.md:363-376`, `387-400`, `411-416`).
- Spec requires durable state and validation evidence in `ValidationState`, plus append-only ledger artifacts (`agentic-harness-spec-v5.2.md:500-509`, `523-564`).
- Current code has plain dataclasses only. There is no persistence layer, no serialization, no stable artifact reference mechanism, no reload semantics, and no ledger integration anywhere in this module.

Impact:
- Restart/recovery claims are unimplemented.
- Evidence can disappear, drift, or be rewritten without detection.

### 6) Reviewer independence is not enforced at all
- Spec requires reviewer runs to be context-isolated from builder runs except for spec, diffs/artifacts, and validation outputs (`agentic-harness-spec-v5.2.md:363-369`).
- Execution plan requires fixed reviewer schema and blocks pass without discussion of missing evidence or untested critical branch (`EXECUTION_PLAN.md:406-416`, `433-438`).
- This module contains no reviewer schema, no reviewer state, no visibility controls, no separation enforcement, and no mechanism limiting reviewer input channels.

Impact:
- Rubber-stamping remains possible.
- A reviewer could see builder rationale or summaries and approve based on framing rather than artifacts.

### 7) Anti-vacuity is shallow and can be bypassed trivially
- Spec anti-vacuity rule: validation must fail if the claimed implementation could be removed or clearly broken while validation still passes (`agentic-harness-spec-v5.2.md:609-610`).
- Execution plan requires a removed/stubbed implementation test that fails (`EXECUTION_PLAN.md:394-404`, `445-449`).
- Current anti-vacuity only checks short strings and a tiny keyword list (`validation.py:143-171`).
- Any plausible-sounding fake string longer than 10 chars passes.

Attack examples that likely pass:
- `"Verified successfully against target behavior in local run."`
- `"Regression suite green; output matches expected."`
- `"Proof artifact captured and reviewed."`

None of these prove the implementation exists.

Impact:
- The implementation does not test the key adversarial property: “delete the code and see what still passes.”

### 8) Ladder ordering is implemented with lexicographic string comparison, not explicit rung ordering
- Ladder filtering uses `if c.level.value <= level.value` (`validation.py:103-106`).
- Enum values are strings: `assert`, `verify`, `cross_check`, `adversarial` (`validation.py:17-22`).
- String comparison does not match ladder order. For example:
  - `'cross_check' <= 'verify'` is true lexicographically
  - `'adversarial' <= 'assert'` is also true because `'adversarial'` sorts before `'assert'`
- This means higher-rigor criteria can leak into lower-rigor runs and vice versa.

Impact:
- The ladder is not reliable even as a filter.
- The test suite misses this bug because it only checks one case (`test_execute_filters_by_level`) and does not probe adversarial lexicographic inversions (`tests/validation/test_validation.py:42-54`).

### 9) Validation result does not feed failure taxonomy or circuit breaker
- Spec requires explicit failure classes and `validation_failure` / `loop_detected` handling (`agentic-harness-spec-v5.2.md:630-649`).
- Execution plan asks whether validation result feeds failure taxonomy and circuit breaker; Phase 3 completion should preserve incomplete state correctly (`EXECUTION_PLAN.md:433-450`).
- This module has no failure classification output, no rejection ledger, no breaker signal, and no mapping from repeated blocked/fail states to retry policy.

Impact:
- Validation failures remain local booleans instead of control signals for orchestration.
- The anti-loop architecture cannot consume this result.

## Findings (non-blocking)

### 1) The module header cites the wrong spec section
- File docstring says `From spec (§15)` for validation ladder and verification system (`validation.py:1-7`).
- In the spec, validation and review are in §12, reviewer separation is §9.9, evidence model is §11.3, and failure taxonomy is §13.
- This is cosmetic, but it hints the implementation may have been built against an outdated or paraphrased mental model.

### 2) Requiredness exists in `Criterion` but is effectively ignored
- `Criterion.required` exists (`validation.py:34-39`), but `ValidationResult.required_fail_count` does not consult actual criterion metadata (`validation.py:77-85`).
- `_is_required()` always returns `True` and is unused.

### 3) Tests are too weak to defend the design intent
- Tests check enum existence, a shallow vacuity heuristic, one blocked case, and pass-rate completion behavior (`tests/validation/test_validation.py:11-130`).
- They do not test:
  - must-pass vs informational semantics
  - contradictory results
  - blocked completion invariants
  - reviewer schema enforcement
  - artifact reachability
  - restart/reload durability
  - failure taxonomy integration
  - lexicographic ladder ordering bug

### 4) Local test execution environment is incomplete
- I attempted to run the test file with `pytest` and `python3 -m pytest`, but `pytest` is not installed in this environment.
- That is not a design defect in the module itself, but it weakens current validation evidence for Phase 3.

## Missing validation matrix items
- Negative test proving a criterion cannot pass on free-form text without an artifact ref.
- Negative test proving missing artifact refs or unreachable artifacts fail validation.
- Test that all-`BLOCKED` required criteria cannot produce `is_complete=True`.
- Test that a failed must-pass gate dominates many passing informational gates.
- Test that empty criteria set and empty gates set cannot produce `PASS` or `complete`.
- Test for contradictory results: criteria pass but gates fail; verdict must remain non-complete.
- Test for reviewer independence: reviewer input must exclude builder rationale.
- Restart/recovery tests for persisted validation state, artifact refs, and reviewer outputs.
- Anti-vacuity test that removes the implementation while preserving fake evidence strings and confirms failure.
- Ladder ordering tests covering all pairwise rung comparisons.
- Tests that validation failures emit `validation_failure` and repeated patterns contribute to circuit breaker / rejection ledger.

## Spec gaps
- The user task references spec §10 for validation and §13 for reviewer harness/evidence, but in the current spec these topics are mainly in §11-§13, with reviewer separation in §9.9. The phase docs should cite canonical sections consistently.
- The spec says reviewer outputs should include criterion assessment, one likely escaped defect, one untested path, and verdict (`agentic-harness-spec-v5.2.md:602-607`), but it does not define a concrete reviewer artifact schema with required fields, IDs, or machine-checkable constraints.
- The spec requires `ValidationState.criterionResults[]` and `gateResults[]` (`agentic-harness-spec-v5.2.md:500-509`) but does not define their schemas precisely enough here to guarantee interoperable implementation.
- “Explicitly unavailable for legitimate reasons” (`agentic-harness-spec-v5.2.md:615`) needs a tighter taxonomy. Otherwise this can become a loophole for waived must-pass gates.
- The spec says artifacts should be immutable and typed (`agentic-harness-spec-v5.2.md:549-564`) but does not require integrity primitives such as content hash, file existence guarantee, or storage backend semantics.

## Recommendations
- Replace the current `VerificationTriple` with a real contract object containing at least:
  - criterion ID
  - build target
  - verification command(s)
  - expected output(s)
  - failure signature(s)
  - must-pass vs informational classification
  - artifact ref(s)
  - execution status
  - verdict
- Add a first-class artifact reference model, not raw evidence strings. Minimum fields:
  - artifact ID
  - type
  - path/URI
  - content hash
  - producer run ID
  - creation timestamp
  - immutability flag
- Make validation verdict computation gate-based, not pass-rate-based.
  - Any failed must-pass gate => not complete
  - Any blocked required evidence => not complete unless explicitly waived with machine-readable rationale
  - Empty criteria or empty must-pass set => fail closed by default
- Fix ladder ordering by using explicit numeric ranks, not string comparison.
- Add machine-checkable reviewer schema and enforcement:
  - covered criteria
  - missing evidence
  - untested critical branch
  - escaped-defect risk
  - verdict
  - reviewer-visible inputs manifest
- Enforce reviewer independence with explicit allowed-input manifests and tests proving builder rationale is excluded.
- Implement persistence/restart behavior for validation state and artifact refs, with reload invariants and ledger events.
- Connect validation outputs to failure taxonomy:
  - emit `validation_failure` when must-pass validation fails
  - feed repeated equivalent failures into rejection ledger / circuit breaker
- Strengthen anti-vacuity from string heuristics to adversarial revalidation:
  - remove/stub implementation
  - rerun executable checks
  - verify verdict flips to fail
- Expand tests to cover all blocking findings above before Phase 3 can be considered signed off.
