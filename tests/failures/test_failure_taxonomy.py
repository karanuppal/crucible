"""Phase 1 validation: Failure taxonomy tests.

Validation matrix requirements:
- Table-driven: concrete failures map to exact next actions
- Unknown failure kind routes to safe fallback
- Budget semantics: environment/dependency don't consume retry budget
- Every supported failure class has one deterministic next action
"""

import pytest

from agentic_harness.failures.taxonomy import (
    FailureClass, NextAction, classify_failure, get_next_action,
    consumes_retry_budget, FailureClassification,
)


class TestDeterministicMapping:
    """Every failure class must map to exactly one next action."""

    @pytest.mark.parametrize("failure_class,expected_action", [
        (FailureClass.AMBIGUITY_BLOCK, NextAction.ASK_USER),
        (FailureClass.ENVIRONMENT_BLOCK, NextAction.FIX_ENVIRONMENT),
        (FailureClass.MISSING_DEPENDENCY, NextAction.REQUEST_DEPENDENCY),
        (FailureClass.ARCHITECTURE_MISMATCH, NextAction.PROPOSE_REVISION),
        (FailureClass.MODEL_LIMITATION, NextAction.CHANGE_ROLE_MODEL_BACKEND),
        (FailureClass.VALIDATION_FAILURE, NextAction.REPAIR_FROM_EVIDENCE),
        (FailureClass.INTEGRATION_CONFLICT, NextAction.ROUTE_TO_INTEGRATOR),
        (FailureClass.LOOP_DETECTED, NextAction.TRIP_CIRCUIT_BREAKER),
    ])
    def test_failure_to_action_mapping(self, failure_class, expected_action):
        result = classify_failure(failure_class)
        assert result.next_action == expected_action

    def test_all_failure_classes_have_mapping(self):
        """Every FailureClass enum value must produce a non-fallback action."""
        for fc in FailureClass:
            action = get_next_action(fc)
            assert action != NextAction.SAFE_FALLBACK, f"{fc} has no defined action"


class TestUnknownFailure:
    """Unknown failure kinds must route to safe fallback."""

    def test_unknown_string_routes_to_fallback(self):
        result = classify_failure("totally_unknown_failure")
        assert result.next_action == NextAction.SAFE_FALLBACK
        assert not result.consumes_retry_budget

    def test_empty_string_routes_to_fallback(self):
        result = classify_failure("")
        assert result.next_action == NextAction.SAFE_FALLBACK

    def test_unknown_does_not_crash(self):
        result = classify_failure("xyzzy_nonsense", description="weird", evidence="none")
        assert isinstance(result, FailureClassification)


class TestBudgetSemantics:
    """Environment and missing-dependency failures should NOT consume retry budget."""

    def test_environment_block_no_budget(self):
        assert not consumes_retry_budget(FailureClass.ENVIRONMENT_BLOCK)

    def test_missing_dependency_no_budget(self):
        assert not consumes_retry_budget(FailureClass.MISSING_DEPENDENCY)

    @pytest.mark.parametrize("failure_class", [
        FailureClass.AMBIGUITY_BLOCK,
        FailureClass.ARCHITECTURE_MISMATCH,
        FailureClass.MODEL_LIMITATION,
        FailureClass.VALIDATION_FAILURE,
        FailureClass.INTEGRATION_CONFLICT,
        FailureClass.LOOP_DETECTED,
    ])
    def test_other_failures_consume_budget(self, failure_class):
        assert consumes_retry_budget(failure_class)


class TestClassifyFailureOutput:
    """classify_failure should return complete, correct FailureClassification."""

    def test_returns_description_and_evidence(self):
        result = classify_failure(
            FailureClass.VALIDATION_FAILURE,
            description="Tests failed",
            evidence="3/10 tests red",
        )
        assert result.description == "Tests failed"
        assert result.evidence == "3/10 tests red"
        assert result.failure_class == FailureClass.VALIDATION_FAILURE

    def test_string_input_for_known_class(self):
        result = classify_failure("ambiguity_block")
        assert result.failure_class == FailureClass.AMBIGUITY_BLOCK
        assert result.next_action == NextAction.ASK_USER

    def test_enum_input(self):
        result = classify_failure(FailureClass.LOOP_DETECTED)
        assert result.next_action == NextAction.TRIP_CIRCUIT_BREAKER
