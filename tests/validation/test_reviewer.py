"""Phase 3 tests: Reviewer independence and report schema."""

import pytest

from crucible.validation.reviewer import (
    ReviewerInput, ReviewerReport, ReviewerVerdict,
    validate_reviewer_input, FORBIDDEN_REVIEWER_INPUT_KEYS,
)


def _valid_criterion_dict(cid="c1"):
    return {
        "criterion_id": cid,
        "description": "test",
        "criterion_class": "must_pass",
        "triple": {
            "build_target": "src/foo.py",
            "verification_command": "pytest tests/foo.py",
            "expected_output": "PASSED",
            "failure_signature": "FAILED",
        },
    }


class TestReviewerIndependence:
    def test_forbidden_builder_rationale_rejected(self):
        raw = {
            "spec": "some spec",
            "criteria": [],
            "artifact_refs": [],
            "builder_rationale": "I did this because...",  # forbidden
        }
        with pytest.raises(ValueError, match="forbidden|disallowed"):
            ReviewerInput.from_raw(raw)
    
    def test_forbidden_chain_of_thought_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "builder_chain_of_thought": "step 1... step 2...",
        }
        with pytest.raises(ValueError, match="forbidden|disallowed"):
            ReviewerInput.from_raw(raw)
    
    def test_valid_input_accepted(self):
        raw = {
            "spec": "spec",
            "criteria": [_valid_criterion_dict()],
            "artifact_refs": [],
            "validation_verdict": {
                "task_id": "t1",
                "status": "complete",
                "must_pass_failures": [],
                "blocked_required": [],
                "reason": "",
                "criterion_results": [],
            },
            "diffs": "diff content",
        }
        inp = ReviewerInput.from_raw(raw)
        assert inp.spec == "spec"
    
    def test_all_forbidden_keys_blocked(self):
        for forbidden_key in FORBIDDEN_REVIEWER_INPUT_KEYS:
            raw = {"spec": "x", "criteria": [], forbidden_key: "leaked"}
            with pytest.raises(ValueError):
                ReviewerInput.from_raw(raw)


class TestReviewerReport:
    def test_approval_without_discussion_rejected(self):
        """Rubber-stamping must be flagged by is_well_formed()."""
        report = ReviewerReport(
            task_id="t1",
            reviewer_run_id="r1",
            covered_criteria=["c1"],
            missing_evidence=[],
            untested_critical_branches=[],
            escaped_defect_risk="",
            verdict=ReviewerVerdict.APPROVE,
            rationale="LGTM",  # trivial
        )
        assert not report.is_well_formed()
    
    def test_approval_with_substantive_rationale_accepted(self):
        report = ReviewerReport(
            task_id="t1",
            reviewer_run_id="r1",
            covered_criteria=["c1"],
            missing_evidence=[],
            untested_critical_branches=[],
            escaped_defect_risk="none identified",
            verdict=ReviewerVerdict.APPROVE,
            rationale="All criteria have executable evidence; adversarial tests cover edge cases including empty inputs and malformed nested data; gates are gate-based not pass-rate.",
        )
        assert report.is_well_formed()
    
    def test_approval_with_missing_evidence_acknowledged(self):
        report = ReviewerReport(
            task_id="t1",
            reviewer_run_id="r1",
            covered_criteria=["c1"],
            missing_evidence=["c2 lacks test_report artifact"],
            untested_critical_branches=[],
            escaped_defect_risk="low",
            verdict=ReviewerVerdict.APPROVE,
            rationale="ok",
        )
        assert report.is_well_formed()
    
    def test_rejection_always_well_formed(self):
        report = ReviewerReport(
            task_id="t1",
            reviewer_run_id="r1",
            covered_criteria=[],
            missing_evidence=[],
            untested_critical_branches=[],
            escaped_defect_risk="",
            verdict=ReviewerVerdict.REJECT,
            rationale="no",
        )
        assert report.is_well_formed()
