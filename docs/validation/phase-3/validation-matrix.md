# Phase 3 Validation Matrix

## Artifacts
| Requirement | Test | Status |
|-------------|------|--------|
| Content hashing | test_create_from_real_file | ✅ |
| Integrity detection (tampering) | test_hash_fails_on_tampered_file | ✅ |
| Missing file rejected | test_missing_file_rejected | ✅ |
| Serialization roundtrip | test_roundtrip | ✅ |

## Criteria & Verification Triples
| Requirement | Test | Status |
|-------------|------|--------|
| Must-pass vs informational class | test_must_pass_gating | ✅ |
| Triple required fields | VerificationTriple schema | ✅ |
| Command provenance tracking | test_matching_command_accepted | ✅ |
| Run provenance tracking | test_artifact_from_wrong_run_rejected | ✅ |

## Validator (Gate-Based)
| Requirement | Test | Status |
|-------------|------|--------|
| Empty criteria fail closed | test_empty_criteria_fails_closed | ✅ |
| No must-pass fails closed | test_no_must_pass_fails_closed | ✅ |
| BLOCKED blocks completion | test_blocked_required_not_complete | ✅ |
| FAIL must-pass blocks | test_must_pass_fail_blocks_completion | ✅ |
| PASS without evidence downgraded | test_pass_without_evidence_downgraded | ✅ |
| Wrong command rejected | test_wrong_command_rejected | ✅ |
| Wrong run rejected | test_artifact_from_wrong_run_rejected | ✅ |
| Tampered artifacts rejected | test_tampered_artifact_rejected | ✅ |
| Orphan results rejected | test_orphan_result_rejected | ✅ |
| Must-pass dominates passing | test_failed_must_pass_dominates_many_passing | ✅ |

## Ladder
| Requirement | Test | Status |
|-------------|------|--------|
| Numeric (not lexicographic) ordering | test_numeric_not_lexicographic | ✅ |
| All pairs correct | test_all_pairs_correct | ✅ |
| Task size mapping | test_*_task_* | ✅ |

## Reviewer Independence
| Requirement | Test | Status |
|-------------|------|--------|
| Top-level forbidden rejected | test_forbidden_builder_rationale_rejected | ✅ |
| Nested forbidden rejected | test_nested_builder_rationale_rejected | ✅ |
| Deeply nested forbidden rejected | test_deeply_nested_forbidden_rejected | ✅ |
| Forbidden in list rejected | test_forbidden_in_list_rejected | ✅ |
| Clean nested accepted | test_clean_nested_accepted | ✅ |
| Rubber-stamp detection | test_approval_without_discussion_rejected | ✅ |

## Anti-Vacuity
| Requirement | Test | Status |
|-------------|------|--------|
| Vacuous detected | test_vacuous_criterion_detected | ✅ |
| Non-vacuous passes | test_non_vacuous_criterion_passes_check | ✅ |
| Restore on error | test_restore_called_even_on_exec_error | ✅ |

## Persistence
| Requirement | Test | Status |
|-------------|------|--------|
| Validation state roundtrip | test_validation_state_roundtrip | ✅ |
| Verdict reload preserves status | test_verdict_reload_preserves_status | ✅ |
| Reviewer report persistence | test_reviewer_report_persistence | ✅ |
