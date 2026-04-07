"""Phase 3 v7 adversarial fixes: exhaustive scalar typing on all leaf fields."""

import pytest

from agentic_harness.validation.reviewer import ReviewerInput


def _valid_triple():
    return {
        "build_target": "src/foo.py",
        "verification_command": "pytest tests/foo.py",
        "expected_output": "PASSED",
        "failure_signature": "FAILED",
    }


class TestScalarCriterionFields:
    def test_criterion_id_must_be_string(self):
        raw = {
            "spec": "x",
            "criteria": [{
                "criterion_id": {"builder_rationale": "secret"},  # dict
                "description": "x",
                "criterion_class": "must_pass",
                "triple": _valid_triple(),
            }],
        }
        with pytest.raises(ValueError, match="must be str"):
            ReviewerInput.from_raw(raw)
    
    def test_description_must_be_string(self):
        raw = {
            "spec": "x",
            "criteria": [{
                "criterion_id": "c1",
                "description": {"builder_thoughts": "hidden"},
                "criterion_class": "must_pass",
                "triple": _valid_triple(),
            }],
        }
        with pytest.raises(ValueError, match="must be str"):
            ReviewerInput.from_raw(raw)
    
    def test_criterion_class_must_be_string(self):
        raw = {
            "spec": "x",
            "criteria": [{
                "criterion_id": "c1",
                "description": "x",
                "criterion_class": ["must_pass"],
                "triple": _valid_triple(),
            }],
        }
        with pytest.raises(ValueError, match="must be str"):
            ReviewerInput.from_raw(raw)


class TestScalarVerdictFields:
    def _base_verdict(self, **overrides):
        v = {
            "task_id": "t1",
            "status": "complete",
            "must_pass_failures": [],
            "blocked_required": [],
            "reason": "ok",
            "criterion_results": [],
        }
        v.update(overrides)
        return v
    
    def test_reason_must_be_string(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "validation_verdict": self._base_verdict(reason={"hidden": "framing"}),
        }
        with pytest.raises(ValueError, match="must be str"):
            ReviewerInput.from_raw(raw)
    
    def test_task_id_must_be_string(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "validation_verdict": self._base_verdict(task_id={"x": "y"}),
        }
        with pytest.raises(ValueError, match="must be str"):
            ReviewerInput.from_raw(raw)
    
    def test_must_pass_failures_must_be_list_of_str(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "validation_verdict": self._base_verdict(must_pass_failures=[{"hidden": "x"}]),
        }
        with pytest.raises(ValueError, match="must be str"):
            ReviewerInput.from_raw(raw)
    
    def test_criterion_results_must_be_list_of_dict(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "validation_verdict": self._base_verdict(criterion_results=["secret"]),
        }
        with pytest.raises(ValueError, match="must be a dict"):
            ReviewerInput.from_raw(raw)
    
    def test_criterion_results_forbidden_key_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "validation_verdict": self._base_verdict(criterion_results=[{
                "criterion_id": "c1",
                "verdict": "pass",
                "builder_rationale": "hidden",
            }]),
        }
        with pytest.raises(ValueError, match="forbidden"):
            ReviewerInput.from_raw(raw)


class TestCleanInputStillAccepted:
    def test_full_clean_input(self):
        raw = {
            "spec": "test spec",
            "criteria": [{
                "criterion_id": "c1",
                "description": "test criterion",
                "criterion_class": "must_pass",
                "triple": _valid_triple(),
            }],
            "artifact_refs": [{
                "artifact_id": "a1",
                "type": "log",
                "path": "/tmp/out.log",
                "content_hash": "abc",
                "producer_run_id": "r1",
                "created_at": 1.0,
                "immutable": True,
            }],
            "validation_verdict": {
                "task_id": "t1",
                "status": "complete",
                "must_pass_failures": [],
                "blocked_required": [],
                "reason": "all passed",
                "criterion_results": [{
                    "criterion_id": "c1",
                    "verdict": "pass",
                }],
            },
            "diffs": "some diff",
        }
        # Should not raise
        ReviewerInput.from_raw(raw)
