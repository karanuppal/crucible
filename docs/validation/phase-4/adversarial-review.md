# Phase 4 Adversarial Review — Scheduling and Memory Foundation

- Verdict: FAIL

## Findings (blocking)

### 1) Memory store does not enforce the host/harness security boundary

The code claims: “this store must NOT accept arbitrary strings from the host conversation context” and “All lessons come from recorded run outcomes.” (`src/agentic_harness/memory/memory_store.py:10-12`)

The implementation does not enforce that claim:
- `LessonSource.POST_MORTEM` is accepted with no `source_run_id` (`memory_store.py:25-30`, `67-98`)
- `add_lesson()` validates only non-empty text plus `source_run_id` for three source types; it does **not** verify that the text originated from a recorded run, reviewer artifact, validation artifact, or postmortem record (`memory_store.py:78-85`)
- `_load()` trusts persisted JSON and does not re-validate provenance (`memory_store.py:156-169`)

Concrete evidence:
- Executed snippet:
  - `MemoryStore().add_lesson('Karan said use his personal SSH key from chat', LessonSource.POST_MORTEM)`
  - Result: accepted successfully as `post_mortem` with empty `source_run_id`
- This means arbitrary host-chat text can be promoted into harness memory with no artifact binding.

Why this is blocking:
- Phase 4’s explicit blocking gate is “no host-memory leakage into harness-owned memory.”
- Current implementation fails that gate.

### 2) Lesson provenance is forgeable

The spec requires harness-owned continuity and explicit separation from host conversational memory. In practice, provenance is just a caller-supplied enum plus optional caller-supplied `source_run_id` (`memory_store.py:67-98`). There is no validation that:
- the run ID exists
- the run produced the lesson
- the reviewer/validation artifact exists
- a postmortem record exists

Concrete evidence:
- Any caller can submit:
  - `source=LessonSource.RUN_OUTCOME, source_run_id='run-123'`
- The store accepts it without checking whether `run-123` is real.
- For `POST_MORTEM`, even that weak check disappears entirely.

Why this is blocking:
- The review prompt explicitly called out “Can provenance be forged?”
- Yes, trivially.
- This undermines trust in persisted lessons and injected retry guidance.

### 3) Machine profile detection is not actually fail-safe

The docstring says detection “Fails safe: if any metric cannot be read, uses a conservative fallback value.” (`src/agentic_harness/scheduler/machine_profile.py:45-49`)

The implementation only catches `ImportError` around `psutil` (`machine_profile.py:61-66`). If `psutil` is present but `virtual_memory()` raises any other exception, detection crashes instead of falling back.

Concrete evidence:
- Executed snippet with a fake `psutil` module whose `virtual_memory()` raises `RuntimeError('boom')`
- Result: `detect_machine_profile()` raised `RuntimeError: boom`

Why this is blocking:
- Phase 4 validation matrix requires missing/unavailable metrics to be handled safely.
- Present-but-failing telemetry is a realistic failure mode and is not handled safely.

## Findings (non-blocking)

### 1) Machine profile can succeed with obviously bogus values

`detect_machine_profile()` does not sanity-check the returned numbers before marking the profile as `source='live'` (`machine_profile.py:99-105`).

Concrete evidence:
- Executed snippet with mocked memory stats: total = 8 GB, available = 64 GB
- Result:
  - `MachineProfile(cpu_count=10, total_memory_gb=8.0, available_memory_gb=64.0, ..., source='live')`
- So detection can “succeed” while producing impossible state (`available > total`).

Impact:
- Scheduler headroom is computed from `available_memory_gb`; impossible inputs can inflate allowed concurrency.

### 2) Heavy-classification bypasses are easy

Current heuristics are narrow regex matches (`src/agentic_harness/scheduler/intensity.py:26-58`). Several near-equivalent heavy commands fall through to medium.

Concrete evidence from executed classification snippet:
- `pytest tests/unit` → `medium`
- `python -m pytest` → `medium`
- `npm ci` → `medium`
- `make test` → `medium`
- `uv run pytest` → `medium`
- `pytest tests/ -q` → `medium`

Impact:
- A user can bypass “looks-light-but-heavy” detection with minor command tweaks.
- The current test corpus is too optimistic relative to real command variation.

### 3) Scheduler is static, not load-aware

The scheduler bases capacity only on the initial profile snapshot and internal estimated task costs (`src/agentic_harness/scheduler/scheduler.py:63-93`). It does not read live CPU or live memory, and it does not update the profile after restart.

Impact:
- “Low-memory/high-CPU” and oscillating-load cases are not actually modeled; they are only representable if the initial profile already encoded them.
- This is weaker than the execution plan’s requirement for forced low-memory/high-CPU and oscillating-load scenarios.

### 4) Contradictory/stale handling is minimal and asymmetric

`mark_contradictory()` only flips one lesson’s status (`memory_store.py:125-130`). There is no conflict-set linkage, no newer-truth preference, no pairwise contradiction tracking, and no surfaced rationale during retrieval. Retrieval simply excludes non-active lessons and sorts active lessons by recency (`memory_store.py:103-115`).

Concrete evidence:
- Added two conflicting lessons for the same tag
- Marked only the newer one contradictory
- Retrieval returned only the older lesson: `['Use pytest -q']`

Impact:
- Contradiction handling depends entirely on correct external marking and can silently preserve stale truth.

### 5) Injection is “audited” only in-memory

`inject_lessons_into_run()` returns an `InjectionRecord` but does not persist it anywhere (`memory_store.py:181-196`). So injection is explicit, but not durably auditable across restart unless some external caller separately saves it.

## Missing validation matrix items

### Machine profile
- No test for impossible but syntactically valid metrics (e.g. `available_memory_gb > total_memory_gb`)
- No test for non-`ImportError` telemetry failures from `psutil`
- No tolerance-based diff against real host command output, despite execution plan requirement
- Persist/reload equivalence test is partial only; test checks a few fields, not full object equality

### Intensity classification
- No fixture coverage for command wrappers/variants:
  - `python -m pytest`
  - `uv run pytest`
  - `pytest tests/unit`
  - `npm ci`
  - `make test`
- No threshold metric proving “classification accuracy meets threshold on curated fixture set”
- No persisted classification/reload test, despite matrix mentioning stability after reload

### Scheduler
- No stress test with live or simulated changing resource availability
- No oscillating-load race/concurrency test
- No mixed burst-dispatch test proving headroom under concurrent dispatch attempts
- No starvation/fairness test (e.g. heavy queue head blocking lighter work)
- Restart test only proves that a running task key remains present after load; it does not prove queue/running correctness, timestamps, or post-restart dispatch behavior

### Memory and lessons
- No negative test for host conversation contamination attempt
- No test that forged `source_run_id` is rejected
- No test that persisted JSON with bad provenance/status is rejected on load
- No restart test for injection audit trail, because no durable audit trail exists
- No retry-path proof that only active lessons are injected from persisted state into a real resumed run

## Recommendations

1. Enforce provenance at the data model boundary, not by convention.
   - Require every lesson to reference a real artifact/ref (run outcome, validation result, reviewer finding, or postmortem record)
   - Treat `POST_MORTEM` as a typed artifact with its own ID, not free text
   - Re-validate provenance on load

2. Make host/harness separation testable and explicit.
   - Add negative tests that attempt to store raw host-chat strings
   - Reject lessons that are not derived from harness-owned records

3. Harden machine profile detection.
   - Catch broader telemetry failures than `ImportError`
   - Sanity-check metrics (`cpu_count >= 1`, `0 < available <= total`, etc.)
   - Set `source` truthfully (`live` vs `fallback` / `cached`)

4. Expand intensity fixtures to real-world command variants.
   - Normalize wrappers (`python -m`, `uv run`, shell prefixes)
   - Add common synonyms (`npm ci`, `make test`, `pytest tests/unit`, `pytest tests/ -q`)
   - Define and report an actual accuracy threshold

5. Upgrade scheduler validation from static unit tests to stress simulation.
   - Simulate changing available memory/CPU over time
   - Exercise burst dispatch, mixed loads, and oscillation
   - Verify headroom preservation under concurrent access or document single-threaded assumptions explicitly

6. Make contradiction handling first-class.
   - Model conflict sets or supersession chains
   - Prefer newer validated truth over merely older active truth
   - Surface contradiction metadata during retrieval

7. Persist injection audit records if “auditable” is a real requirement.
   - Otherwise, weaken the claim in docs/tests to match reality.
