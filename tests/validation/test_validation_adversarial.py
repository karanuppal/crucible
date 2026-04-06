"""Phase 3 second-pass adversarial tests — addresses review v2 blockers."""

import pytest

from agentic_harness.validation.artifact import (
    ArtifactRef, ArtifactType, create_artifact_ref,
)
from agentic_harness.validation.criterion import (
    Criterion, CriterionClass, CriterionResult, CriterionVerdict, VerificationTriple,
)
from agentic_harness.validation.validator import Validator, TaskCompletionStatus
from agentic_harness.validation.reviewer import ReviewerInput, ReviewerReport, ReviewerVerdict
from agentic_harness.validation.persistence import ValidationStateRecord
from agentic_harness.validation.ladder import LadderRung


def _mk_triple(cmd="pytest tests/test_foo.py"):
    return VerificationTriple(
        build_target="src/foo.py",
        verification_command=cmd,
        expected_output="PASSED",
        failure_signature="FAILED",
    )


def _mk_criterion(cid="c1", cmd="pytest tests/test_foo.py"):
    return Criterion(
        criterion_id=cid,
        description="test",
        criterion_class=CriterionClass.MUST_PASS,
        triple=_mk_triple(cmd),
    )


# ─────────────────────────────────────────────────────────────────
# Blocker 1: Recursive forbidden-key filtering
# ─────────────────────────────────────────────────────────────────

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


class TestNestedForbiddenKeys:
    def test_nested_builder_rationale_rejected(self):
        c = _valid_criterion_dict()
        c["builder_rationale"] = "leaked"
        raw = {"spec": "x", "criteria": [c]}
        with pytest.raises(ValueError, match="forbidden|disallowed"):
            ReviewerInput.from_raw(raw)
    
    def test_deeply_nested_forbidden_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "validation_verdict": {
                "task_id": "t1",
                "status": "complete",
                "must_pass_failures": [],
                "blocked_required": [],
                "reason": "",
                "criterion_results": [],
                "builder_chain_of_thought": "secret",  # forbidden key at this level
            },
        }
        with pytest.raises(ValueError, match="forbidden|disallowed"):
            ReviewerInput.from_raw(raw)
    
    def test_forbidden_in_list_rejected(self):
        c1 = _valid_criterion_dict("c1")
        c2 = _valid_criterion_dict("c2")
        c2["builder_thoughts"] = "leak"
        raw = {"spec": "x", "criteria": [c1, c2]}
        with pytest.raises(ValueError, match="forbidden|disallowed"):
            ReviewerInput.from_raw(raw)
    
    def test_clean_nested_accepted(self):
        raw = {
            "spec": "x",
            "criteria": [_valid_criterion_dict()],
            "validation_verdict": {
                "task_id": "t1",
                "status": "complete",
                "must_pass_failures": [],
                "blocked_required": [],
                "reason": "ok",
                "criterion_results": [],
            },
        }
        # Should not raise
        ReviewerInput.from_raw(raw)


# ─────────────────────────────────────────────────────────────────
# Blocker 2: Evidence provenance linkage
# ─────────────────────────────────────────────────────────────────

class TestEvidenceProvenance:
    def test_wrong_command_rejected(self, tmp_path):
        """Artifact produced by wrong command should be rejected."""
        v = Validator()
        criterion = _mk_criterion("c1", cmd="pytest tests/test_foo.py")
        
        p = tmp_path / "other.log"
        p.write_text("PASSED")
        art = create_artifact_ref(str(p), ArtifactType.LOG, "run-1")
        
        # Result claims PASS but with command that doesn't match criterion's triple
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            executed_command="echo FAKE",  # wrong command
            run_id="run-1",
        )
        
        verdict = v.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
        assert "c1" in verdict.must_pass_failures
    
    def test_matching_command_accepted(self, tmp_path):
        v = Validator()
        cmd = "pytest tests/test_foo.py"
        criterion = _mk_criterion("c1", cmd=cmd)
        
        p = tmp_path / "out.log"
        p.write_text("PASSED")
        art = create_artifact_ref(str(p), ArtifactType.LOG, "run-1")
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            executed_command=cmd,
            run_id="run-1",
        )
        
        verdict = v.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.COMPLETE
    
    def test_artifact_from_wrong_run_rejected(self, tmp_path):
        """Artifact must be produced by the same run as the result."""
        v = Validator()
        cmd = "pytest tests/test_foo.py"
        criterion = _mk_criterion("c1", cmd=cmd)
        
        p = tmp_path / "out.log"
        p.write_text("PASSED")
        # Artifact producer = run-OTHER
        art = create_artifact_ref(str(p), ArtifactType.LOG, "run-OTHER")
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            executed_command=cmd,
            run_id="run-1",  # different from artifact producer
        )
        
        verdict = v.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
    
    def test_orphan_result_rejected(self):
        """Result for a criterion not in the criteria set is rejected."""
        v = Validator()
        criterion = _mk_criterion("c1")
        orphan_result = CriterionResult(
            criterion_id="c-nonexistent",
            verdict=CriterionVerdict.PASS,
        )
        
        with pytest.raises(ValueError, match="[Oo]rphan"):
            v.validate("t1", [criterion], [orphan_result])
    
    def test_tampered_artifact_rejected(self, tmp_path):
        """Integrity check: tampered file should not count as evidence."""
        v = Validator()
        cmd = "pytest tests/test_foo.py"
        criterion = _mk_criterion("c1", cmd=cmd)
        
        p = tmp_path / "out.log"
        p.write_text("PASSED")
        art = create_artifact_ref(str(p), ArtifactType.LOG, "run-1")
        
        # Tamper after hash captured
        p.write_text("TAMPERED")
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            executed_command=cmd,
            run_id="run-1",
        )
        
        verdict = v.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE


# ─────────────────────────────────────────────────────────────────
# Blocker 3: Persistence/restart
# ─────────────────────────────────────────────────────────────────

class TestPersistence:
    def test_validation_state_roundtrip(self, tmp_path):
        cmd = "pytest tests/test_foo.py"
        criterion = _mk_criterion("c1", cmd=cmd)
        
        p = tmp_path / "out.log"
        p.write_text("PASSED")
        art = create_artifact_ref(str(p), ArtifactType.LOG, "run-1")
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            executed_command=cmd,
            run_id="run-1",
        )
        
        validator = Validator()
        verdict = validator.validate("t1", [criterion], [result])
        
        state = ValidationStateRecord(
            task_id="t1",
            criteria=[criterion],
            results=[result],
            verdict=verdict,
            current_rung=LadderRung.UNIT,
        )
        
        state_path = tmp_path / "state.json"
        state.save(str(state_path))
        
        loaded = ValidationStateRecord.load(str(state_path))
        
        assert loaded.task_id == "t1"
        assert len(loaded.criteria) == 1
        assert loaded.criteria[0].criterion_id == "c1"
        assert len(loaded.results) == 1
        assert loaded.verdict.status == TaskCompletionStatus.COMPLETE
        assert loaded.current_rung == LadderRung.UNIT
    
    def test_verdict_reload_preserves_status(self, tmp_path):
        criterion = _mk_criterion("c1")
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.BLOCKED,
        )
        
        validator = Validator()
        verdict = validator.validate("t1", [criterion], [result])
        
        state = ValidationStateRecord(
            task_id="t1",
            criteria=[criterion],
            results=[result],
            verdict=verdict,
        )
        
        path = tmp_path / "state.json"
        state.save(str(path))
        loaded = ValidationStateRecord.load(str(path))
        
        assert loaded.verdict.status == TaskCompletionStatus.INCOMPLETE
        assert "c1" in loaded.verdict.blocked_required
    
    def test_reviewer_report_persistence(self, tmp_path):
        criterion = _mk_criterion("c1")
        
        report = ReviewerReport(
            task_id="t1",
            reviewer_run_id="r1",
            covered_criteria=["c1"],
            missing_evidence=[],
            untested_critical_branches=["edge case x"],
            escaped_defect_risk="low",
            verdict=ReviewerVerdict.REJECT,
            rationale="Found issue in edge handling",
        )
        
        state = ValidationStateRecord(
            task_id="t1",
            criteria=[criterion],
            results=[],
            reviewer_reports=[report],
        )
        
        path = tmp_path / "state.json"
        state.save(str(path))
        loaded = ValidationStateRecord.load(str(path))
        
        assert len(loaded.reviewer_reports) == 1
        assert loaded.reviewer_reports[0].verdict == ReviewerVerdict.REJECT
        assert "edge case x" in loaded.reviewer_reports[0].untested_critical_branches
