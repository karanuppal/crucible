"""Phase 3 v8 fix: criterion_results strict schema closure."""

import pytest
from crucible.validation.reviewer import ReviewerInput


def _base(cr_list):
    return {
        "spec": "x",
        "criteria": [],
        "validation_verdict": {
            "task_id": "t1",
            "status": "complete",
            "must_pass_failures": [],
            "blocked_required": [],
            "reason": "ok",
            "criterion_results": cr_list,
        },
    }


class TestCriterionResultsSchemaClosure:
    def test_unknown_key_in_criterion_result_rejected(self):
        raw = _base([{
            "criterion_id": "c1",
            "verdict": "pass",
            "details": {"hidden": "data"},  # not in allowlist
        }])
        with pytest.raises(ValueError, match="disallowed"):
            ReviewerInput.from_raw(raw)
    
    def test_context_key_rejected(self):
        raw = _base([{
            "criterion_id": "c1",
            "verdict": "pass",
            "context": "builder framing",
        }])
        with pytest.raises(ValueError, match="disallowed"):
            ReviewerInput.from_raw(raw)
    
    def test_nested_dict_under_actual_output_rejected(self):
        """Even in allowed fields, nested dicts are rejected."""
        raw = _base([{
            "criterion_id": "c1",
            "verdict": "pass",
            "actual_output": {"builder_rationale": "secret"},
        }])
        with pytest.raises(ValueError, match="must be str"):
            ReviewerInput.from_raw(raw)
    
    def test_nested_list_under_error_rejected(self):
        raw = _base([{
            "criterion_id": "c1",
            "verdict": "fail",
            "error": ["nested", "framing"],
        }])
        with pytest.raises(ValueError, match="must be str"):
            ReviewerInput.from_raw(raw)
    
    def test_clean_criterion_result_accepted(self):
        raw = _base([{
            "criterion_id": "c1",
            "verdict": "pass",
            "actual_output": "PASSED",
            "error": "",
            "executed_command": "pytest",
            "run_id": "r1",
        }])
        ReviewerInput.from_raw(raw)  # should not raise
    
    def test_minimal_criterion_result_accepted(self):
        raw = _base([{
            "criterion_id": "c1",
            "verdict": "pass",
        }])
        ReviewerInput.from_raw(raw)
