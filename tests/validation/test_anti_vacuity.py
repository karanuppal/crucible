"""Phase 3 tests: Anti-vacuity adversarial revalidation."""

import pytest

from crucible.validation.anti_vacuity import check_vacuity
from crucible.validation.criterion import (
    Criterion, CriterionClass, VerificationTriple,
)


def _mk_criterion():
    return Criterion(
        criterion_id="c1",
        description="test",
        criterion_class=CriterionClass.MUST_PASS,
        triple=VerificationTriple(
            build_target="foo.py",
            verification_command="run-test",
            expected_output="PASSED",
            failure_signature="FAILED",
        ),
    )


class TestVacuityDetection:
    def test_vacuous_criterion_detected(self):
        """If stubbed impl still passes, criterion is vacuous."""
        criterion = _mk_criterion()
        
        # Mock executor returns PASSED even with stub
        def fake_exec(cmd):
            return (0, "All tests PASSED")
        
        stub_called = []
        restore_called = []
        
        result = check_vacuity(
            criterion,
            execute_command=fake_exec,
            stub_impl=lambda: stub_called.append(1),
            restore_impl=lambda: restore_called.append(1),
        )
        
        assert result.is_vacuous
        assert stub_called == [1]
        assert restore_called == [1]
    
    def test_non_vacuous_criterion_passes_check(self):
        """If stubbed impl fails as expected, criterion is sound."""
        criterion = _mk_criterion()
        
        def fake_exec(cmd):
            return (1, "FAILED: impl missing")
        
        result = check_vacuity(
            criterion,
            execute_command=fake_exec,
            stub_impl=lambda: None,
            restore_impl=lambda: None,
        )
        
        assert not result.is_vacuous
    
    def test_restore_called_even_on_exec_error(self):
        """Finally-block must always restore the implementation."""
        criterion = _mk_criterion()
        restore_called = []
        
        def failing_exec(cmd):
            raise RuntimeError("boom")
        
        with pytest.raises(RuntimeError):
            check_vacuity(
                criterion,
                execute_command=failing_exec,
                stub_impl=lambda: None,
                restore_impl=lambda: restore_called.append(1),
            )
        
        assert restore_called == [1]
