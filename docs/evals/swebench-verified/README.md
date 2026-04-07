# SWE-bench Verified with Crucible

This directory contains a **setup-only starter pack** for evaluating Crucible against real SWE-bench Verified tasks.

The goal is simple:
- keep the benchmark metadata local
- point Crucible at real tasks
- let Crucible own the solving loop

This folder is intentionally **not** a custom benchmark harness with hidden gold patches or hand-written task solutions.

## What is here

- `evals/swebench-verified/mini-pilot.json`
  - a 3-task warm-up batch
- `evals/swebench-verified/starter-batch.json`
  - a broader 8-task starter set
- `docs/evals/swebench-verified/problems/*.md`
  - local copies of the benchmark problem statements + useful metadata

## What is not here

- gold patches
- benchmark-specific solving logic
- hand-authored fixes
- benchmark cheating shortcuts

## Why this exists

SWE-bench tasks are a good stress test for the core v5.4 promise:
- can Crucible take a real software problem,
- validate honestly,
- fail honestly,
- choose the next action deterministically,
- repair and re-test,
- and drive the task toward a real terminal outcome?

This starter pack lets you test that without re-scraping the benchmark every run.

## Included starter tasks

### Mini-pilot
1. `astropy__astropy-14309`
   - tiny warm-up bug
   - good for first-pass loop validation
2. `django__django-11133`
   - small behavioral/type issue
3. `astropy__astropy-13033`
   - validation / error-message correctness

### Starter batch
The 8-task batch broadens coverage across Astropy and Django with small-to-medium difficulty tasks.

## Recommended usage flow

For a single benchmark task:

1. clone the target repository
2. checkout the benchmark `base_commit`
3. feed Crucible the raw `problem_statement`
4. use `FAIL_TO_PASS` as the main target
5. keep `PASS_TO_PASS` as regression guardrails
6. let Crucible own the execution/repair loop

## Example workflow

```text
Select task from mini-pilot.json
→ checkout target repo at base_commit
→ create/load Crucible run
→ execute build / validate / repair / review loop
→ inspect resulting evidence and terminal status
```

## Important benchmark rule

Do **not** preload the gold patch or solution into the runtime. The point is to evaluate the harness honestly.

## Suggested first benchmark

Start with:
- `astropy__astropy-14309`

Why:
- it is small enough to validate the loop quickly
- failures are easier to inspect
- it is a good first sanity check for build → fail → repair → retest behavior

## Relationship to OpenClaw

If you are using Crucible from OpenClaw, the usual flow is:
- OpenClaw handles the user/task surface
- Crucible handles runtime execution semantics
- this SWE-bench pack provides the benchmark task data

So this folder is **input data + local documentation**, not the runtime itself.

## If you are new to this repo

Read in this order:
1. `README.md`
2. `docs/crucible-spec-v5.4.md`
3. `docs/execution-plan-v5.4.md`
4. this file
5. `tests/runtime/test_closed_loop_runtime_e2e.py`

That should give you enough context to understand how benchmark evaluation is supposed to work.