# Adversarial Review — Phase 3 Validation and Review Foundation (v3)

Verdict: FAIL

## Summary

I re-read both prior adversarial reviews, the Phase 3 execution plan, the validation matrix, the source modules, and the test suite. I also ran the required test command:

- `uv run pytest tests/validation/ -v`
- Result: **46/46 passed**

That said, **Phase 3 is still not ready for signoff**.

The prior blockers around shallow evidence, lexicographic ladder ordering, `BLOCKED` completion, and nested forbidden reviewer keys are materially improved or fixed. But fresh inspection still finds **trust-boundary holes** and **execution-plan deliverables missing in code**, especially around:

- forged evidence provenance
- missing validation ladder executor behavior
- incomplete verification-triple enforcement
- persistence not covering all required Phase 3 state/artifacts
- reviewer isolation relying on denylist scanning instead of a strict input contract

A PASS verdict would be too generous.

## Blocker status table (all 10)

| # | Prior blocker | Status | Notes |
|---|---|---|---|
| 1 | Validation could pass on unverifiable string evidence | FIXED | Validation now requires artifact-backed evidence; narrative strings alone no longer pass. |
| 2 | `BLOCKED` required criteria could still yield complete state | FIXED | `Validator.validate()` returns `INCOMPLETE` for blocked/missing must-pass criteria. |
| 3 | Verdicts used pass-rate heuristics instead of gate semantics | FIXED | Gate-based completion replaced pass-rate logic. |
| 4 | Verification triple missing core contract fields | PARTIAL | Better than v1: has build target / command / expected output / failure signature. Still missing full enforcement and durable execution linkage required for Phase 3 signoff. |
| 5 | No persistence / restart coverage for required validation state | PARTIAL | There is now JSON roundtrip persistence for criteria/results/verdict/reviewer reports/current rung. But not all required Phase 3 state is persisted, and durability is still weak. |
| 6 | Reviewer independence not enforced | PARTIAL | Forbidden keys are now recursively blocked. But reviewer intake still is not strict allowlist validation, so non-forbidden builder framing can still be smuggled in. |
| 7 | Ladder ordering bug from lexicographic comparison | FIXED | `IntEnum` ordering and pairwise tests close the original bug. |
| 8 | Nested forbidden reviewer keys could bypass top-level filtering | FIXED | Recursive scan now catches nested dict/list cases covered in v2. |
| 9 | Evidence provenance not enforced strongly enough | PARTIAL | Wrong command / wrong run / tampered files are rejected. But provenance is still self-attested and forgeable. |
| 10 | Persistence/restart evidence for reviewer outputs and validation state absent | PARTIAL | Roundtrip tests now exist, but required Phase 3 restart/recovery semantics remain incomplete. |

## New findings

### 1) Evidence provenance can still be gamed by forging metadata
**Still blocking.**

The validator checks:
- artifact exists
- artifact hash matches
- `executed_command == criterion.triple.verification_command`
- `run_id` matches artifact `producer_run_id`

But all of that provenance is still **self-reported by the submitted `CriterionResult` / `ArtifactRef` data structure**. There is no execution attestation, no trusted run ledger lookup, no signed run record, and no independent binding between:

- the actual command that ran
- the actual run that produced the artifact
- the criterion being validated

Attack shape:
- create a real file with favorable output
- construct `ArtifactRef(... producer_run_id="run-123" ...)`
- submit `CriterionResult(... executed_command=<expected>, run_id="run-123")`
- validator accepts it because the tuple is internally consistent

This is better than v1/v2, but it is **not strong provenance**. It is consistency checking over untrusted input.

### 2) Validation ladder executor is still missing
**Blocking vs execution plan.**

Phase 3 deliverables require a **validation ladder executor** with:
- rung-by-rung execution
- failure-at-rung blocking semantics
- partial completion / resume behavior
- rung transcript / per-rung outputs

Current `ladder.py` contains only:
- enum ordering helpers
- `next_rung()`
- task-size mapping

That fixes the old ordering bug, but it is **not a ladder executor**.

There is no implementation that:
- runs rungs in order
- records per-rung outcomes
- prevents later rungs from masking earlier failures
- resumes from a persisted partial rung state

This is a direct miss against the execution plan and validation packet requirements.

### 3) Verification triples are not actually enforced as a system boundary
**Blocking vs execution plan.**

`VerificationTriple.is_well_formed()` exists, but there is no mechanism shown here that rejects malformed/incomplete triples **before task start or signoff**, which the plan explicitly requires.

Missing enforcement examples:
- no validator refusal when a criterion contains an empty triple field
- no task/build boundary that demands complete triples before execution
- no persisted linkage from triple to execution artifact set beyond string equality on command

So the schema exists, but the **contract is not enforced where it matters**.

### 4) Persistence is improved, but not truly complete or durable for all required Phase 3 state
**Still blocking for signoff.**

What now exists:
- `ValidationStateRecord`
- JSON save/load for criteria, results, verdict, rung, reviewer reports
- tests for roundtrip and reviewer report persistence

What is still missing or weak:
- no persisted anti-vacuity result model
- no persisted criterion→evidence mapping report artifact
- no persisted blocked-signoff example / reviewer workflow artifact model
- no validation ladder transcript persistence because no ladder executor exists
- no atomic write / crash-safe save protocol
- no corrupted-state recovery or fail-closed reload tests

So persistence is no longer absent, but it is still **insufficient for the full Phase 3 signoff packet**.

### 5) Reviewer isolation is denylist-based, not strict-contract based
**Observation leaning blocking.**

Recursive forbidden-key scanning fixed the specific v2 bypass. But the intake model still does **not** enforce a strict schema/allowlist over all reviewer-visible content.

Example:
- a builder can place framing text under an allowed-looking nested key such as `criteria[*].notes`, `validation_verdict.context`, or `diffs_metadata.summary`
- as long as the field name is not one of the forbidden tokens, it passes

That means the system blocks only known-bad key names, not builder-private or manipulative content generically.

So to the specific question “can forbidden reviewer keys still sneak in via some structure?” the answer is:
- **those exact forbidden keys:** likely no, based on current recursive scan
- **builder framing under other key names:** yes

For a true trust boundary, reviewer input should be normalized to a strict allowlisted schema, not merely scanned for a few banned names.

### 6) Anti-vacuity remains narrower than the plan implies
**Observation.**

The anti-vacuity helper is materially better than the old keyword heuristic. But it still decides vacuity using:
- exit code
- substring match on `expected_output`

It still does not:
- use `failure_signature`
- prove the verification command actually exercised `build_target`
- persist anti-vacuity outcomes as durable state
- integrate anti-vacuity result into a broader signoff packet model

This is solid progress, but not yet a full Phase 3 trust mechanism.

## Adversarial answers to the requested questions

### 1) All 10 previous blockers: FIXED / PARTIAL / STILL BLOCKING?
See table above.

Bottom line:
- **Fixed:** 1, 2, 3, 7, 8
- **Partial:** 4, 5, 6, 9, 10
- **Still signoff-blocking overall:** yes

### 2) Can forbidden reviewer keys still sneak in via some structure?
**Probably not for the exact forbidden key names** currently listed, because recursive scanning now walks nested dicts/lists.

But **reviewer contamination can still sneak in under different field names**, because the system does not enforce a strict allowlisted reviewer-input schema all the way down.

### 3) Can evidence provenance still be gamed (e.g., forging `executed_command`)?
**Yes.**

Current provenance checks are consistency checks over caller-supplied metadata. There is no trusted execution record or signed run provenance. A forged but internally consistent `CriterionResult` + `ArtifactRef` can still satisfy validation.

### 4) Is persistence truly durable for all required state?
**No.**

Roundtrip JSON persistence exists for some state, but not all required Phase 3 state/artifacts, and not with crash-safe durability semantics.

### 5) Any new vulnerabilities introduced by the fixes?
**Not severe new vulnerabilities, but a new false sense of trust risk exists.**

The rewritten design looks much stronger and has passing tests, but some guarantees are still only local consistency checks, not authoritative proof. The biggest risk is **over-trusting provenance and persistence because the APIs now look mature**.

### 6) What's still missing vs execution plan matrix for Phase 3 signoff?
Missing or unproven items include:

- validation ladder executor
- rung-by-rung transcript / per-rung outputs
- resume-from-partial-rung execution
- rejection of incomplete/ambiguous verification triples at the system boundary
- full criterion→evidence mapping artifact/report
- orphan evidence detection at system/report level
- durable anti-vacuity result persistence
- reviewer workflow artifacts beyond raw report roundtrip
- blocked-signoff example artifact
- stronger proof that reviewer input is constrained to allowed fields only

## Signoff recommendation

**Do not sign off Phase 3 yet.**

Minimum bar before PASS:
- implement a real validation ladder executor with persisted rung progress and transcripts
- enforce verification triple completeness before task start/signoff, not just via helper method
- replace self-attested provenance with trusted run-record linkage
- persist all required Phase 3 state/artifacts, including anti-vacuity outcomes and ladder transcripts
- tighten reviewer input to a strict allowlisted schema, not denylist scanning alone

Current state is **substantially improved** and the 46-test slice is green, but this is best described as:
- strong second rewrite
- not yet Phase 3 signoff-ready
