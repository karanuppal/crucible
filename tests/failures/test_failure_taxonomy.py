"""Tests for the thin v6.1 failure taxonomy."""

import pytest

from crucible.failures.taxonomy import (
    FailureClass, FailureClassification, NextAction, classify_failure,
    consumes_retry_budget, get_next_action,
)


class TestDeterministicMapping:
    @pytest.mark.parametrize("failure_class,expected_action", [
        (FailureClass.RETRYABLE, NextAction.CONTINUE_AUTONOMOUSLY),
        (FailureClass.NEEDS_USER_INPUT, NextAction.ASK_USER),
        (FailureClass.STUCK_OR_REPEATING, NextAction.FORCE_STRATEGY_SHIFT),
        (FailureClass.TERMINAL_NONRECOVERABLE, NextAction.STOP_WITH_EVIDENCE),
    ])
    def test_failure_to_action_mapping(self, failure_class, expected_action):
        result = classify_failure(failure_class)
        assert result.next_action == expected_action

    def test_all_failure_classes_have_mapping(self):
        for fc in FailureClass:
            action = get_next_action(fc)
            assert action != NextAction.SAFE_FALLBACK, f"{fc} has no defined action"


class TestUnknownFailure:
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
    def test_needs_user_input_does_not_consume_retry_budget(self):
        assert not consumes_retry_budget(FailureClass.NEEDS_USER_INPUT)

    @pytest.mark.parametrize("failure_class", [
        FailureClass.RETRYABLE,
        FailureClass.STUCK_OR_REPEATING,
        FailureClass.TERMINAL_NONRECOVERABLE,
    ])
    def test_other_failures_consume_budget(self, failure_class):
        assert consumes_retry_budget(failure_class)


class TestClassifyFailureOutput:
    def test_returns_description_and_evidence(self):
        result = classify_failure(
            FailureClass.RETRYABLE,
            description="Tests failed",
            evidence="3/10 tests red",
        )
        assert result.description == "Tests failed"
        assert result.evidence == "3/10 tests red"
        assert result.failure_class == FailureClass.RETRYABLE

    def test_string_input_for_known_class(self):
        result = classify_failure("needs_user_input")
        assert result.failure_class == FailureClass.NEEDS_USER_INPUT
        assert result.next_action == NextAction.ASK_USER

    def test_enum_input(self):
        result = classify_failure(FailureClass.STUCK_OR_REPEATING)
        assert result.next_action == NextAction.FORCE_STRATEGY_SHIFT
