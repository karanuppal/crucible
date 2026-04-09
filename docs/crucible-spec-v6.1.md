# Crucible Specification v6.1

**Status:** Draft for review  
**Date:** 2026-04-08  
**Supersedes:** `docs/crucible-spec-v6.md` where they conflict

---

## 1. Why v6.1 exists

v6 moved in the right direction: it recognized that Crucible should not give up at the first sign of trouble and should use the LLM to keep the software execution loop moving.

But v6 still over-specified the recovery layer.

The main problems with v6 were:
- too many named failure/recovery categories
- too much implication that specific categories map to fixed prompts or rigid lanes
- too much distinction between “old” attempt types and “new LLM” attempt types
- recovery budgets that were too conservative for the intended level of autonomy

v6.1 keeps the core insight from v6:

> the harness should be deterministic in its loop control, but creative in its problem-solving.

But it simplifies the control plane dramatically.

The new principle is:

> **Keep the metadata layer thin. Keep the evidence layer rich. Let the LLM reason over the full failure context.**

---

## 2. Core model

Crucible has two distinct jobs:

1. **Control-plane job**
   - decide whether to continue, pause, shift strategy, or stop
   - enforce budgets
   - prevent loops
   - preserve durable state
   - expose truthful status

2. **Problem-solving job**
   - interpret failures
   - propose fixes
   - try alternative approaches
   - install dependencies
   - repair environments
   - modify code
   - verify outcomes

In v6.1:
- the **harness** owns the control plane
- the **LLM worker** owns the problem-solving

That means Crucible should not try to encode a highly specific ontology of failure causes in the control plane.
It only needs enough classification to govern the loop.

---

## 3. Four control-plane classifications

v6.1 uses exactly four top-level runtime classifications.

### 3.1 `retryable`
Meaning:
- Crucible should continue autonomously.
- The task is still solvable without human intervention.
- The LLM should receive the full failure context and try to fix it.

Typical examples:
- tests failing
- implementation bug
- import error
- dependency issue that may be installable
- environment/toolchain issue that may be fixable
- build failure

Why this exists:
- This is the default autonomous bucket.
- It tells the harness: keep going, consume autonomous budget, and do not ask the user yet.

### 3.2 `needs_user_input`
Meaning:
- Progress depends on a human decision, approval, or unavailable input.

Typical examples:
- ambiguous product choice
- missing credential the system cannot obtain or safely infer
- missing external secret or token
- explicit approval required
- contradictory requirements requiring human choice

Why this exists:
- The harness needs an explicit pause gate.
- It prevents the LLM from hallucinating a decision or pretending authority it does not have.

### 3.3 `stuck_or_repeating`
Meaning:
- Crucible is not merely failing; it is failing in a way that indicates search collapse, repetition, or no meaningful progress.
- The next move must be materially different.

Typical examples:
- same normalized failure signature recurring
- repeated shallow fixes
- repeated environment oscillation
- multiple attempts with no measurable progress

Why this exists:
- This is the anti-loop category.
- It forces a strategy shift without immediately stopping the run.

### 3.4 `terminal_nonrecoverable`
Meaning:
- Under the current scope, authority, tools, and attempted strategies, Crucible should stop.

Typical examples:
- all relevant autonomous strategies exhausted with evidence of no progress
- repository/tool access impossible under current permissions
- task out of allowed scope
- hard external dependency unavailable with no viable workaround

Why this exists:
- The harness needs an honest terminal state.
- It gives the user a clear “we stopped, here is why, here is what would unblock it” outcome.

---

## 4. What classification is for — and what it is not for

### 4.1 Classification is for control, not diagnosis

These four classes exist to answer only a few questions:
- should Crucible keep going autonomously?
- should Crucible ask the user?
- should Crucible force a strategy change?
- should Crucible stop?

That is all.

### 4.2 Classification is not a detailed failure ontology

The top-level class should **not** try to encode:
- exact root cause
- exact fix type
- exact prompting lane
- exact tool invocation

Those belong in the **evidence packet** and in the LLM’s reasoning process.

### 4.3 No rigid prompt-per-class mapping

v6.1 explicitly rejects the idea that each class implies a fixed canned prompt.

Instead:
- the class influences **control policy**
- the LLM still gets the **raw failure dump + structured evidence + attempt history**
- prompts may be lightly shaped by class, but not reduced to rigid per-class templates

---

## 5. Rich evidence under a thin metadata layer

The control-plane classification is intentionally thin.
The evidence layer is where detail belongs.

Every failure/recovery cycle should persist a structured evidence packet containing, as available:
- failing command
- exit code
- normalized stdout/stderr excerpts
- workspace state summary
- files touched
- tests failing
- artifacts produced
- normalized signature
- install/tooling commands already tried
- prior attempt summaries
- whether progress was made
- whether the failure appears repeated
- whether external authority/input is missing

Optional hints may be attached, but they are **hints**, not top-level classes:
- `dependency_hint`
- `environment_hint`
- `network_hint`
- `credential_hint`
- `test_failure_hint`
- `tooling_hint`

These exist to help the LLM orient quickly and to improve observability.
They must not become a second hidden classification system.

---

## 6. Attempt types in v6.1

Attempt types remain useful, but their purpose is clarified.

### 6.1 Attempt types are role/phase semantics

Attempt types describe the role of a pass through the loop, not whether an LLM is used.

Core attempt types:
- `build`
- `repair`
- `debug`
- `review`
- `salvage`
- `integrate`
- `revalidate`

All of these **may use LLM workers** depending on the execution backend.

That means:
- `build` can be LLM-driven
- `repair` can be LLM-driven
- `debug` can be LLM-driven
- `review` can be LLM-driven

The distinction is **not** “LLM vs non-LLM.”
The distinction is what the runtime expects the attempt to accomplish.

### 6.2 v6.1 removes the need for many new attempt types

v6 introduced extra attempt types like:
- `env_repair`
- `dep_resolve`
- `creative_repair`
- `debug_analysis`
- `research_fix`

v6.1 removes these as first-class attempt types.

Why:
- they were overfitting control-plane structure to problem-solving style
- they made the system feel more complicated than necessary
- they implied special LLM-only lanes in a confusing way

Instead, these become **strategy modes inside existing attempt types**.

Examples:
- a `repair` attempt may focus on dependency resolution
- a `repair` attempt may focus on environment correction
- a `debug` attempt may focus on root-cause analysis
- a `repair` attempt under `stuck_or_repeating` may explicitly require a different strategy

This keeps the runtime model simpler.

---

## 7. Recovery behavior

### 7.1 Default rule

When something fails, Crucible should:
1. persist evidence
2. classify using the 4-class control plane
3. decide whether to continue, pause, shift strategy, or stop
4. send the full failure context to the LLM worker
5. require verification after any attempted fix

### 7.2 `retryable` behavior

If classified as `retryable`:
- continue autonomously
- do not ask user
- consume the appropriate autonomous attempt budget
- pass raw failure context and evidence to the LLM
- allow the LLM to choose the concrete fix approach

Example:
- `No module named pytest`
- class = `retryable`
- evidence includes dependency/tooling hint + attempted commands
- next attempt type likely `repair`
- LLM decides whether to use `uv pip install`, `pip install`, project-specific setup, or another method

### 7.3 `needs_user_input` behavior

If classified as `needs_user_input`:
- pause the autonomous loop
- emit a targeted blocker packet
- specify exactly what input/approval/secret/decision is needed
- preserve all evidence so the run can resume cleanly

### 7.4 `stuck_or_repeating` behavior

If classified as `stuck_or_repeating`:
- do **not** immediately stop
- force a materially different attempt strategy
- require the worker to summarize prior failed approaches before trying again
- optionally switch worker/model/backend/workspace basis if available
- spend from a larger “deep recovery” budget

This class is the main anti-loop mechanism.

### 7.5 `terminal_nonrecoverable` behavior

If classified as `terminal_nonrecoverable`:
- stop the loop
- emit a terminal evidence-backed outcome
- include:
  - what was tried
  - why those attempts failed
  - why continued autonomy is unjustified
  - what would unblock future progress, if anything

---

## 8. Budget model

v6.1 keeps budgets, but simplifies and expands them.

### 8.1 Budget categories

Suggested default budgets:
- `build_attempt_budget = 3`
- `repair_attempt_budget = 8`
- `debug_attempt_budget = 4`
- `review_rejection_budget = 3`
- `salvage_attempt_budget = 4`
- `integration_attempt_budget = 3`
- `deep_recovery_budget = 6`

### 8.2 Why these are higher than v6

The earlier v6 draft used budgets that were too low for the intended autonomy level.

v6.1 increases them because the goal is not:
- “try once or twice, then give up”

The goal is:
- “search meaningfully before escalating”

### 8.3 What `deep_recovery_budget` means

This budget is spent when the run is in `stuck_or_repeating` mode and the harness is forcing materially different strategies.

This gives Crucible room to:
- switch approaches
- switch prompt framing
- widen search
- try more substantial recovery moves

without immediately terminating the task.

---

## 9. Loop control vs LLM freedom

This is the key v6.1 boundary.

### 9.1 The harness decides:
- whether the run is autonomous, paused, stuck, or terminal
- whether budgets remain
- whether repetition is occurring
- whether the next attempt must materially differ
- whether user input is required
- whether the run should stop

### 9.2 The LLM decides:
- what concrete fix to try
- how to interpret the raw failure details
- how to modify code or environment
- what alternative approach is most promising
- how to adapt based on full context

### 9.3 Design rule

The harness should not over-specify the repair lane.
The LLM should not silently own loop policy.

That is the balance.

---

## 10. Example: Astropy benchmark under v6.1

### v6.0 style
- `No module named pytest`
- classify `missing_dependency`
- route to `dep_resolve`
- special recovery lane

### v6.1 style
- `No module named pytest`
- classify `retryable`
- evidence packet includes:
  - dependency hint
  - commands attempted
  - project setup signals
- next attempt type = `repair`
- prompt says, in effect:
  - here is the failure
  - here is the prior state
  - solve it
  - verify it

This is simpler and closer to the real product goal.

---

## 11. Prompting philosophy

v6.1 prefers a general recovery prompt with light shaping instead of rigid class-specific prompts.

### 11.1 Base recovery prompt should include
- task goal
- current failure
- raw command output
- structured evidence packet
- prior attempts summary
- explicit instruction to verify after fixing

### 11.2 Prompt shaping may vary by class

Examples:
- `retryable`: “continue autonomously and solve this”
- `needs_user_input`: not a recovery prompt; emit blocker packet
- `stuck_or_repeating`: “you must try a materially different strategy than prior attempts”
- `terminal_nonrecoverable`: no further worker execution; produce final evidence-backed stop reason

This is much lighter than v6’s per-lane prompting system.

---

## 12. Migration from v6 to v6.1

### 12.1 Remove over-specific recovery lanes
Collapse v6’s named recovery attempt types into:
- existing attempt types
- plus class-aware strategy guidance

### 12.2 Replace detailed failure classes with four top-level control classes
Use only:
- `retryable`
- `needs_user_input`
- `stuck_or_repeating`
- `terminal_nonrecoverable`

### 12.3 Preserve rich evidence
Move specificity into:
- evidence packets
- hints
- attempt history
- progress/repetition signals

### 12.4 Increase autonomy budgets
Adopt larger default budgets to better match intended persistence.

---

## 13. Success criteria for v6.1

v6.1 is successful if:
1. The metadata layer is thin and legible.
2. The harness keeps enough policy control to prevent drift.
3. The LLM still receives the full raw failure context.
4. Attempt types no longer imply “LLM vs non-LLM.”
5. Recovery is more persistent before escalation.
6. The system is simpler to understand than v6 while remaining more capable than v5.4.

---

## 14. Summary

v6.1 keeps the important v6 idea:
- Crucible should not give up too early.
- The LLM should be used to keep the execution loop moving.

But v6.1 simplifies the architecture by:
- reducing the control plane to four coarse classes
- moving detail into evidence instead of taxonomy
- treating attempt types as role semantics, not LLM semantics
- increasing budgets to support real autonomy

The result should be a harness that is:
- deterministic in loop control
- flexible in problem solving
- simpler to reason about
- less overfit to named recovery lanes
- closer to the actual product goal
