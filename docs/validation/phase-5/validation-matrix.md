# Phase 5 Validation Matrix

## Existing-Project Intake

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| Clean repo classified | test_clean_repo_classified | python+uv+pytest+CI+README+git → "clean" | ✅ |
| Messy repo classified | test_messy_repo_classified | language but missing some signals → "messy" | ✅ |
| Ambiguous surfaces uncertainty | test_ambiguous_repo_surfaces_uncertainty | no_language_detected flag | ✅ |
| Broken archetype reachable | test_broken_archetype_classified | lang + 3+ missing critical → "broken" | ✅ |
| No unittest hallucination | test_bare_tests_dir_no_unittest_invented | empty tests/ no longer invents framework | ✅ |
| TOML-based parsing | test_*_pyproject_* | tomllib reads tool table + deps, not raw text | ✅ |
| Save/load roundtrip | test_save_load_roundtrip | JSON persistence | ✅ |
| Missing repo raises | test_missing_repo_raises | FileNotFoundError | ✅ |

## Worktree Isolation

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| Create worktree | test_create_worktree | git worktree add | ✅ |
| Changes don't bleed into main | test_worktree_changes_dont_bleed_into_main | main_repo_clean() | ✅ |
| Concurrent worktrees isolated | test_concurrent_worktrees_isolated | separate file sets | ✅ |
| Remove worktree | test_remove_worktree | status="removed" | ✅ |
| State survives restart | test_state_survives_restart | JSON persistence | ✅ |
| Missing worktree marked stale | test_missing_worktree_marked_stale | _reconcile() | ✅ |
| Git-broken fail-closed | (in _reconcile logic) | git_worktree_paths=None → all stale | ✅ |
| Missing repo raises | test_missing_repo_raises | WorktreeError | ✅ |

## Greenfield Bootstrap

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| Full bootstrap creates structure | test_full_bootstrap_creates_structure | pyproject, README, .gitignore, CI, src/, tests/, .git | ✅ |
| All steps completed | test_all_steps_completed | every step in completed_steps | ✅ |
| Resume from partial state | test_resume_from_partial_state | re-run is no-op | ✅ |
| State persisted | test_state_persisted | reload roundtrip | ✅ |
| Resume repairs missing artifacts | test_resume_repairs_missing_artifacts | _verify_step_artifacts re-runs | ✅ |
| Resume doesn't claim false complete | test_resume_doesnt_falsely_claim_complete | rebuilds when artifacts missing | ✅ |
| GitHub remote creation (optional) | (gh CLI integration) | create_github_repo + push_to_github steps | ✅ |

## First-Working-Version Gate

| Requirement | Test | Evidence | Status |
|-------------|------|----------|--------|
| Scaffold-only fails | test_scaffold_only_with_no_test_files_fails | no test_*.py → fail | ✅ |
| Forged output rejected | test_forged_output_with_no_real_tests_fails | "1 passed" + no files → fail | ✅ |
| Real tests succeed | test_passing_tests_with_real_files_succeed | independent pytest verification | ✅ |
| Failing tests fail gate | test_failing_tests_fail_gate | independent pytest sees failure | ✅ |
| Proof artifact created | test_proof_artifact_created | durable file written | ✅ |
| Forgery via test file presence rejected | test_forgery_with_no_test_files_rejected | AST-checked test files | ✅ |
| Forgery via stdout function names rejected | test_forgery_with_failing_real_test_rejected | independent pytest is source of truth | ✅ |
| User command not executed in strict mode | test_user_command_not_executed_in_strict_mode | trust anchor only | ✅ |
| User command tamper rejected | test_user_command_tamper_with_test_file_rejected | hash binding | ✅ |
| Hidden file mutation detected | test_hidden_file_mutation_detected | full project hash incl hidden | ✅ |
| Hidden dir mutation detected | test_hidden_dir_mutation_detected | full project hash incl hidden | ✅ |

## Blocking Gates Cleared

- [x] No silent hallucinated repo classification
- [x] No mutation bleed into main checkout during parallel worktree tests
- [x] Every supported bootstrap type demonstrated end-to-end
- [x] First-working-version requires executable proof, not scaffold presence alone
