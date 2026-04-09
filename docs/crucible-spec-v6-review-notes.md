# Crucible v6.1 reviewer notes

Date: 2026-04-08
Status: PASS

## Review scope
- `docs/crucible-spec-v6.1.md`
- failure control-plane implementation
- selector/runtime integration
- blocker packet targeting
- budget defaults and naming
- attempt-type semantics
- architecture docs
- relevant tests

## Final review pass

### Findings checked
1. Top-level failure taxonomy is exactly four classes.
   - Result: PASS
2. `needs_user_input` emits targeted blocker packets with the right reason class.
   - Result: PASS
   - Evidence: missing-secret cases now produce `credential_required` with a concrete target; explicit approvals produce `approval_required`; generic ambiguity stays `clarification_needed`.
3. Selector/runtime policy avoids hidden v6-style named recovery lanes.
   - Result: PASS
   - Evidence: retryable environment/tooling failures now route through coarse `repair` control actions with hints/metadata rather than a dedicated `environment_fix` lane.
4. Attempt types remain role semantics, not backend semantics.
   - Result: PASS
5. Budgets match v6.1 naming/defaults, including `deep_recovery_budget`.
   - Result: PASS
6. Docs describe the v6.1 thin-control-plane model rather than v6 lane taxonomy.
   - Result: PASS
7. Relevant targeted and broader suites pass.
   - Result: PASS

## Fixes made during the review loop
- Added targeted user-input requirement extraction in runtime failure classification.
- Included concrete blocker metadata in evidence packets so the runtime can surface the exact missing secret / approval / clarification target.
- Collapsed environment/tooling follow-up back into coarse `repair` routing.
- Removed lingering runtime handling for the old `environment_fix` action.
- Updated `docs/architecture.md` to describe the v6.1 control plane and current budget model.
- Added/updated regression tests for targeted blocker packets and coarse repair routing.
- Enforced `deep_recovery_budget` at execution time for `stuck_or_repeating` / repeated-failure debug escalations so runtime spend now matches selector policy.
- Added explicit recovery-prompt shaping for v6.1: task goal, current failure, raw output, structured evidence packet, prior-attempts summary, and mandatory post-fix verification.
- Forced `stuck_or_repeating` prompts to require summarizing prior failed approaches and trying a materially different strategy.
- Added regression coverage proving deep-recovery spend does not leak into ordinary debug budget usage.

## Final reviewer verdict
Clean pass. Implementation matches the v6.1 control-plane model, blocker packets are correctly targeted, deep-recovery spend now aligns with control-plane decisions, stuck/repeating retries are explicitly forced into materially different strategies with prior-attempt summaries, and recovery prompts/docs/tests are aligned with v6.1.
