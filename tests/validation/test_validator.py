"""Phase 3 tests: Validator gate-based verdict computation."""

import pytest

from crucible.validation.artifact import (
    ArtifactRef, ArtifactType, create_artifact_ref,
)
from crucible.validation.criterion import (
    Criterion, CriterionClass, CriterionResult, CriterionVerdict, VerificationTriple,
)
from crucible.validation.validator import (
    Validator, TaskCompletionStatus,
)


def _make_triple():
    return VerificationTriple(
        build_target="src/foo.py",
        verification_command="pytest tests/test_foo.py",
        expected_output="PASSED",
        failure_signature="FAILED",
    )


def _mp_criterion(cid="c1"):
    return Criterion(
        criterion_id=cid,
        description="x",
        criterion_class=CriterionClass.MUST_PASS,
        triple=_make_triple(),
    )


def _info_criterion(cid="c2"):
    return Criterion(
        criterion_id=cid,
        description="x",
        criterion_class=CriterionClass.INFORMATIONAL,
        triple=_make_triple(),
    )


class TestFailClosed:
    def test_empty_criteria_fails_closed(self):
        v = Validator()
        result = v.validate("t1", [], [])
        assert result.status == TaskCompletionStatus.FAILED
    
    def test_no_must_pass_fails_closed(self):
        v = Validator()
        result = v.validate("t1", [_info_criterion()], [])
        assert result.status == TaskCompletionStatus.FAILED


class TestMustPassGating:
    def test_blocked_required_not_complete(self, tmp_path):
        """All must-pass BLOCKED → INCOMPLETE (not COMPLETE)."""
        v = Validator()
        criterion = _mp_criterion()
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.BLOCKED,
        )
        
        verdict = v.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
        assert "c1" in verdict.blocked_required
    
    def test_must_pass_fail_blocks_completion(self):
        v = Validator()
        criterion = _mp_criterion()
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.FAIL,
        )
        
        verdict = v.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
        assert "c1" in verdict.must_pass_failures
    
    def test_must_pass_with_real_evidence_completes(self, tmp_path):
        v = Validator()
        criterion = _mp_criterion()
        
        # Create real evidence artifact
        p = tmp_path / "result.log"
        p.write_text("PASSED")
        art = create_artifact_ref(str(p), ArtifactType.LOG, "run-1")
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            actual_output="PASSED",
            executed_command=criterion.triple.verification_command,  # provenance
            run_id="run-1",
        )
        
        verdict = v.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.COMPLETE


class TestVacuousEvidenceRejection:
    def test_pass_without_evidence_downgraded(self):
        """A PASS with no artifact refs must not produce complete."""
        v = Validator()
        criterion = _mp_criterion()
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[],  # no evidence
        )
        
        verdict = v.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
        assert "c1" in verdict.must_pass_failures
    
    def test_pass_with_unreachable_artifact_downgraded(self):
        """A PASS with artifact refs that don't exist on disk must be downgraded."""
        v = Validator()
        criterion = _mp_criterion()
        
        # Create ref pointing to nonexistent file
        bad_ref = ArtifactRef(
            artifact_id="fake",
            type=ArtifactType.LOG,
            path="/tmp/nonexistent-xyz-12345.log",
            content_hash="deadbeef",
            producer_run_id="r1",
            created_at=0.0,
        )
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[bad_ref],
        )
        
        verdict = v.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE


class TestMustPassDominatesPassing:
    def test_failed_must_pass_dominates_many_passing(self, tmp_path):
        """One failed must-pass blocks completion even with many passing."""
        v = Validator()
        
        # Set up 1 failing must-pass + 3 passing must-pass
        criteria = [_mp_criterion(f"c{i}") for i in range(4)]
        
        p = tmp_path / "good.log"
        p.write_text("PASSED")
        art = create_artifact_ref(str(p), ArtifactType.LOG, "r1")
        
        results = [
            CriterionResult("c0", CriterionVerdict.FAIL),
            CriterionResult("c1", CriterionVerdict.PASS, [art]),
            CriterionResult("c2", CriterionVerdict.PASS, [art]),
            CriterionResult("c3", CriterionVerdict.PASS, [art]),
        ]
        
        verdict = v.validate("t1", criteria, results)
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
        assert "c0" in verdict.must_pass_failures


class TestMissingResultsBlocked:
    def test_missing_result_for_must_pass_blocks(self):
        """A must-pass criterion with no result at all = blocked."""
        v = Validator()
        criterion = _mp_criterion()
        
        verdict = v.validate("t1", [criterion], [])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
        assert "c1" in verdict.blocked_required
