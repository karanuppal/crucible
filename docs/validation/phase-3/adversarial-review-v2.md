# Adversarial Review — Phase 3 Validation and Review Foundation (v2)

Verdict: FAIL

## Status of previous blockers

1. **Validation passing on unverifiable strings** — **FIXED**
   - Old failure mode: any plausible narrative evidence string could pass.
   - New implementation requires `ArtifactRef` evidence, and `Validator.validate()` downgrades `PASS` to `FAIL` when `CriterionResult.has_real_evidence()` is false.
   - Evidence:
     - `src/agentic_harness/validation/artifact.py`
     - `src/agentic_harness/validation/criterion.py`
     - `src/agentic_harness/validation/validator.py`
   - Tests cover missing and unreachable artifacts.

2. **`is_complete=True` with `BLOCKED` criteria** — **FIXED**
   - New validator marks missing or `BLOCKED` must-pass criteria as `blocked_required` and returns `INCOMPLETE`.
   - `ValidationVerdict.is_complete` is derived strictly from `status == COMPLETE`.
   - Evidence:
     - `src/agentic_harness/validation/validator.py`
     - `tests/validation/test_validator.py::test_blocked_required_not_complete`

3. **Pass-rate verdict instead of gate-based** — **FIXED**
   - The rewritten validator explicitly rejects pass-rate heuristics and computes completion from must-pass gate semantics only.
   - Evidence:
     - `src/agentic_harness/validation/validator.py`
   - This is a real architectural fix, not just a test patch.

4. **VerificationTriple missing fields** — **PARTIAL**
   - Fixed relative to the old implementation: the new `VerificationTriple` now includes:
     - `build_target`
     - `verification_command`
     - `expected_output`
     - `failure_signature`
   - Still incomplete relative to the full Phase 3 contract:
     - no explicit artifact refs in the triple
     - no must-pass/informational classification inside the triple itself
     - no structured expected-output schema (substring vs regex vs exact match is undocumented)
     - no durable execution-status linkage
   - The criterion object carries some of this elsewhere, so this is much better than before, but not fully closed as a schema foundation.

5. **No persistence** — **STILL BLOCKING**
   - Phase 3 execution plan explicitly requires restart/recovery tests for ladder execution, triples, criterion→evidence mapping, anti-vacuity, and reviewer outputs.
   - This rewrite adds `to_dict/from_dict` for `ArtifactRef` and `Criterion`, but there is still no persistence layer, no `ValidationState`, no ledger integration, no restart semantics, and no tests proving reload correctness.
   - Evidence:
     - Spec §11.1 / `ValidationState`
     - Execution Plan Phase 3 restart rows
     - absence of persistence code in the new modules
   - This remains a blocker for Phase 3 signoff.

6. **Reviewer independence not enforced** — **PARTIAL**
   - Improvement: top-level forbidden reviewer keys such as `builder_rationale` and `builder_chain_of_thought` are rejected.
   - Remaining gap: the sanitization only checks top-level keys of `raw`. Forbidden builder-private material can still be smuggled inside nested structures like `criteria`, `validation_verdict`, or arbitrary nested dict/list payloads.
   - Example bypass:
     - `{"spec": "x", "criteria": [{"id": "c1", "builder_rationale": "secret"}]}`
     - This passes `ReviewerInput.from_raw()` today.
   - So the prior blocker is improved but not fully fixed.

7. **Ladder lexicographic bug** — **FIXED**
   - Old bug: rung ordering compared strings lexicographically.
   - New ladder uses `IntEnum` with explicit numeric ranking and pairwise tests.
   - Evidence:
     - `src/agentic_harness/validation/ladder.py`
     - `tests/validation/test_ladder.py`

## New findings

### Blocking findings

1. **Reviewer forbidden-key filtering is shallow and bypassable through nested structures**
   - `ReviewerInput.from_raw()` checks only `set(raw.keys()) & FORBIDDEN_REVIEWER_INPUT_KEYS`.
   - It does not recursively inspect nested dicts/lists.
   - That means builder-private fields can be hidden inside allowed containers:
     - `criteria[*].builder_rationale`
     - `validation_verdict.builder_chain_of_thought`
     - arbitrary nested metadata blobs
   - This matters because reviewer independence in the spec is about visible information, not just top-level field names.
   - Impact:
     - reviewer isolation can be violated while all current tests still pass
     - the system can be framed by builder rationale disguised as nested data

2. **Persistence/restart coverage required by Phase 3 is still absent**
   - This was already a previous blocker and remains one.
   - New code does not model persisted validation state, reviewer report persistence, ladder checkpoint persistence, or evidence-link reload guarantees.
   - The execution plan explicitly requires restart/recovery validation for all of these.
   - Impact:
     - Phase 3 cannot claim durable trust semantics yet
     - evidence and verdict relationships are not proven to survive interruption

3. **Criterion→evidence mapping is weaker than the execution plan requires**
   - The plan requires every criterion to link to at least one executable check and one artifact, plus orphan detection.
   - The current validator checks only whether a result marked `PASS` has at least one reachable artifact.
   - It does **not** verify:
     - that the artifact came from the criterion’s `verification_command`
     - that the command actually ran
     - that the artifact corresponds to the right criterion instead of a recycled unrelated file
     - that orphan evidence is detected
   - A trivially existing but wrong artifact can therefore satisfy `has_real_evidence()`.
   - Example attack:
     - criterion claims API behavior verified by `pytest tests/test_api.py`
     - evidence artifact is an unrelated existing log file from another run containing `PASSED`
     - validator accepts it because existence, not provenance, is enforced
   - Impact:
     - the narrative-evidence problem is fixed, but evidence provenance is still under-specified and unenforced

### Non-blocking findings

1. **Anti-vacuity can still be gamed if the verification command is itself weak**
   - The anti-vacuity check is directionally correct and much better than the old keyword heuristic.
   - But `check_vacuity()` decides vacuity using:
     - `exit_code == 0`
     - `expected_output in output`
   - It does not validate:
     - `failure_signature`
     - exact match vs regex semantics
     - that the command meaningfully exercised `build_target`
   - If the verification command is poorly chosen or always prints the expected token, anti-vacuity will misclassify.
   - This is more a missing enforcement layer around triple quality than a flaw in the vacuity function alone.

2. **Artifact integrity exists but validator uses only existence, not integrity**
   - `ArtifactRef.verify_integrity()` exists.
   - `CriterionResult.has_real_evidence()` only calls `a.exists()`, not `a.verify_integrity()`.
   - So a tampered artifact at the same path still counts as “real evidence” during validation.
   - This is weaker than the stated immutability goal in spec §11.3.

3. **Validator accepts extra/unmapped results silently**
   - `results` may contain criterion IDs not present in `criteria`, and they are not rejected.
   - This is not the most serious issue, but a stricter contract would reject unknown criterion results to prevent noisy or forged attachments.

4. **Reviewer report schema is only lightly enforced**
   - `ReviewerReport.is_well_formed()` mainly blocks ultra-short rubber stamps.
   - It does not require:
     - at least one escaped-defect risk description for approvals
     - at least one untested path discussion for non-trivial approvals
     - coverage consistency between `covered_criteria` and actual criteria set
   - Better than nothing, but still fairly permissive.

## Attack analysis

### 1. Can vacuity be bypassed by using a trivially existing but wrong artifact?
**Yes.**

- The validator only checks that at least one artifact exists on disk.
- It does not tie the artifact back to:
  - the current criterion
  - the current run
  - the triple’s verification command
  - the expected output
- So a wrong but existing artifact can satisfy validation.
- This means the old “free-form string evidence” blocker is fixed, but a weaker variant remains: “free-floating artifact existence” can still stand in for true evidence linkage.

### 2. Can forbidden reviewer keys sneak in via nested structure?
**Yes.**

- Top-level forbidden keys are blocked.
- Nested forbidden keys are not inspected.
- This is a real reviewer-independence bypass and should be treated as blocking.

### 3. Is anti-vacuity actually adversarial or can it be gamed?
**Partially adversarial; still gameable.**

What is good:
- it does the right style of check: stub/remove implementation, rerun verification, expect failure
- this is materially stronger than string heuristics

What is still gameable:
- weak verification commands can still pass after stubbing
- success is detected by substring match on `expected_output`
- `failure_signature` is never used
- there is no enforcement that `stub_impl` actually broke the real target
- there is no requirement that the anti-vacuity challenge be integrated into overall signoff

Conclusion:
- the anti-vacuity primitive is directionally correct and much improved
- the surrounding enforcement is still not strong enough to make Phase 3 pass

## Missing validation matrix items

Compared with the Phase 3 execution plan, the following remain missing or unproven:

1. **Validation ladder executor behavior**
   - The code defines rung ordering helpers, but not an actual ladder executor that runs rungs in order, records rung-by-rung outputs, or resumes from a partial rung completion.
   - The plan explicitly calls for rung-by-rung transcript and interruption/resume behavior.

2. **Verification triple rejection before signoff or start**
   - `VerificationTriple.is_well_formed()` exists, but there is no enforcement path showing malformed or ambiguous triples are rejected before task start/signoff.
   - No tests exercise a task/build refusing incomplete triples at the system boundary.

3. **Criterion→evidence orphan detection**
   - No test or implementation proves detection of:
     - orphan criteria
     - orphan evidence
     - evidence linked to the wrong criterion

4. **Persistence/restart tests for triples, evidence, reviewer outputs, anti-vacuity, and ladder progress**
   - Entire row family is absent.

5. **Reviewer blocked-signoff examples**
   - The plan requires blocked-signoff examples where reviewer attempts to pass while missing evidence or leaving untested critical branches unresolved.
   - Current tests only check a shallow `is_well_formed()` heuristic.

6. **Integration with task/build completion state and post-review gates**
   - The validator returns a task-local verdict, but there is no `TaskState` / `BuildState` completion integration proving spec §12.7 behavior.

7. **Required signoff artifacts for Phase 3**
   - No implementation here produces:
     - validation ladder transcript
     - criterion-evidence map
     - anti-vacuity report
     - reviewer schema examples
     - blocked-signoff example

8. **Failure-taxonomy integration**
   - Phase 3 and spec §13 imply validation outcomes should feed `validation_failure` and anti-loop protection.
   - This wiring is still absent.

## Recommendations

1. **Make reviewer sanitization recursive and allowlist-based**
   - Walk nested dict/list structures.
   - Reject any occurrence of forbidden builder-private keys anywhere in the tree.
   - Consider stripping unknown keys entirely rather than merely checking top-level names.

2. **Strengthen evidence linkage from existence to provenance**
   - Each `CriterionResult` should record the specific executed command/run that produced each artifact.
   - Validate that evidence artifacts are linked to the criterion’s triple, not just present on disk.
   - Detect orphan evidence and unknown criterion results.

3. **Use artifact integrity checks during validation**
   - `CriterionResult.has_real_evidence()` should require `exists()` and `verify_integrity()`.
   - Otherwise immutability is asserted but not enforced at verdict time.

4. **Finish the persistence layer for Phase 3, not Phase 4+**
   - Add durable serialization/storage for:
     - validation verdicts
     - criterion results
     - reviewer reports
     - ladder progress
     - anti-vacuity outcomes
   - Add restart/reload tests matching the execution plan.

5. **Upgrade reviewer schema enforcement**
   - For approvals, require:
     - covered criteria list
     - escaped defect risk
     - at least one untested path or explicit declaration that none exist with rationale
     - explicit missing-evidence handling
   - Make this machine-validated, not heuristic string length.

6. **Implement a real ladder executor**
   - Numeric rung ordering is fixed, but the plan requires actual rung execution, blocking semantics, transcripts, and resume behavior.

7. **Tighten anti-vacuity semantics**
   - Use structured expected-output matching.
   - Use `failure_signature` as part of evaluation.
   - Require proof that the challenged command exercised the intended target.
   - Integrate anti-vacuity results into task/build completion gates, not as a standalone helper only.

## Review notes

- I attempted to run the Phase 3 test slice directly with `python3 -m pytest ...`, but `pytest` is not installed in the current environment.
- The repository does declare `pytest` in `pyproject.toml` dev dependencies and in `uv.lock`, so this is an environment gap, not evidence that tests are absent.
- This review is therefore based on direct source/spec/test inspection rather than executed test confirmation.
