# Phase 6 build notes

Implemented against `docs/crucible-spec-v7.3.2.md` only.

## Phase 6 deliverables completed
- Re-ran a representative SWE-bench starter task (`astropy__astropy-14309`) against the current runtime to verify current failure attribution.
- Hardened Python existing-repo environment readiness in `src/crucible/environment/existing_repo.py` so provisioning only succeeds when the detected validation surface is actually runnable.
- Added durable readiness-check metadata to `.crucible/environment.json`:
  - `readiness_checks`
  - `readiness_failures`
- Updated architecture and benchmark docs to match the shipped v7.3.2 runtime instead of older v5.4/v6.1 descriptions.
- Added a Phase 6 rerun note documenting the current benchmark result and why it is now an honest environment failure instead of a misleading provisioning success.

## Concrete hardening change
- For Python repos that detect `pytest` as the test tool, environment readiness now requires:
  - `.venv/bin/python -m pytest --version`
- If that check fails, provisioning records:
  - `status: failed`
  - `failure_class: environment_block`
  - the exact readiness failure message
- This closes the gap documented in the earlier SWE-bench batch report where `.crucible/environment.json` could say `provisioned` even though `pytest` was missing.

## Tests added / updated
- `tests/environment/test_existing_repo.py`
  - successful Python provisioning now records the pytest readiness check
  - installed-sentinel environments without runnable pytest are rejected
  - provisioning fails honestly when pytest is not runnable even after `uv sync`

## Eval rerun performed
- Command:
  - `uv run crucible --runs-dir <tmp> run evals/swebench-verified/generated-plans/astropy__astropy-14309.plan.json --workspace-root /Users/millieclaw/Projects/swebench-workspaces/astropy__astropy-14309 --jsonl`
- Result:
  - terminal `failed`
  - durable failure reason: `python environment missing runnable pytest: ... No module named pytest`
- Why this matters:
  - the run now fails for a concrete, inspectable environment/tooling reason
  - it no longer over-claims successful provisioning for a broken validation surface

## Docs cleanup completed
- `docs/architecture.md`
  - rewritten to describe the shipped v7.3.2 architecture, durable artifact layout, environment readiness contract, and honest backend claims
- `docs/evals/swebench-verified/README.md`
  - updated to separate runtime-truth evaluation from backend-solving capability
- `docs/evals/swebench-verified/v7.3.2-rerun-note.md`
  - added current rerun evidence

## Operational lesson integrated
- Phase 6 now encodes the lesson that environment provisioning must prove the requested validator/test tool is runnable before claiming readiness.
