"""Phase 3 tests: Validation ladder and anti-vacuity."""

import pytest

from agentic_harness.validation.validation import (
    VerificationLevel, Verdict, Criterion, Evidence, VerificationTriple,
    ValidationLadder, ValidationResult, is_vacuous, TaskCompletion,
)


class TestVerificationLevels:
    def test_levels_are_defined(self):
        assert len(VerificationLevel) == 4
        assert VerificationLevel.ASSERT is not None
        assert VerificationLevel.VERIFY is not None
        assert VerificationLevel.CROSS_CHECK is not None
        assert VerificationLevel.ADVERSARIAL is not None


class TestAntiVacuity:
    def test_short_content_is_vacuous(self):
        e = Evidence(type="test", content="ok", source="test")
        assert is_vacuous(e)
    
    def test_todo_is_vacuous(self):
        e = Evidence(type="test", content="TODO: implement", source="test")
        assert is_vacuous(e)
    
    def test_placeholder_is_vacuous(self):
        e = Evidence(type="test", content="placeholder", source="test")
        assert is_vacuous(e)
    
    def test_real_evidence_passes(self):
        e = Evidence(
            type="test",
            content="All 85 tests passed with no failures",
            source="pytest"
        )
        assert not is_vacuous(e)


class TestValidationLadder:
    def test_execute_filters_by_level(self):
        criteria = [
            Criterion("c1", "basic", VerificationLevel.ASSERT),
            Criterion("c2", "verify", VerificationLevel.VERIFY),
            Criterion("c3", "cross", VerificationLevel.CROSS_CHECK),
        ]
        
        ladder = ValidationLadder(criteria)
        result = ladder.execute("t1", VerificationLevel.ASSERT)
        
        assert len(result.triples) == 1
        assert result.triples[0].criterion_id == "c1"
    
    def test_blocked_without_evidence_at_verify_level(self):
        criteria = [
            Criterion("c1", "verify me", VerificationLevel.VERIFY, required=True),
        ]
        
        ladder = ValidationLadder(criteria)
        result = ladder.execute("t1", VerificationLevel.VERIFY)
        
        assert result.triples[0].verdict == Verdict.BLOCKED
    
    def test_results_have_pass_count(self):
        criteria = [
            Criterion("c1", "assert me", VerificationLevel.ASSERT),
        ]
        
        def gather(cid, tid):
            return Evidence(type="test", content="passed", source="test")
        
        ladder = ValidationLadder(criteria, evidence_gatherer=gather)
        result = ladder.execute("t1", VerificationLevel.ASSERT)
        
        assert result.pass_count >= 0


class TestTaskCompletion:
    def test_complete_when_all_pass(self):
        result = ValidationResult(
            task_id="t1",
            level=VerificationLevel.ASSERT,
            triples=[
                VerificationTriple("c1", verdict=Verdict.PASS),
                VerificationTriple("c2", verdict=Verdict.PASS),
            ]
        )
        
        assert TaskCompletion.determine(result) == "complete"
    
    def test_failed_when_most_fail(self):
        result = ValidationResult(
            task_id="t1",
            level=VerificationLevel.ASSERT,
            triples=[
                VerificationTriple("c1", verdict=Verdict.PASS),
                VerificationTriple("c2", verdict=Verdict.FAIL),
                VerificationTriple("c3", verdict=Verdict.FAIL),
            ]
        )
        
        assert TaskCompletion.determine(result) == "failed"
    
    def test_partial_when_some_pass(self):
        result = ValidationResult(
            task_id="t1",
            level=VerificationLevel.ASSERT,
            triples=[
                VerificationTriple("c1", verdict=Verdict.PASS),
                VerificationTriple("c2", verdict=Verdict.PASS),
                VerificationTriple("c3", verdict=Verdict.FAIL),
                VerificationTriple("c4", verdict=Verdict.FAIL),
            ]
        )
        
        assert TaskCompletion.determine(result) == "partial"
    
    def test_is_blocked(self):
        result = ValidationResult(
            task_id="t1",
            level=VerificationLevel.ASSERT,
            triples=[
                VerificationTriple("c1", verdict=Verdict.PASS),
                VerificationTriple("c2", verdict=Verdict.BLOCKED),
            ]
        )
        
        assert TaskCompletion.is_blocked(result)