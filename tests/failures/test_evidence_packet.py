"""Tests for failure evidence packet."""

import pytest

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket


class TestFailureEvidencePacket:
    def test_valid_packet_creation(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="task-1-attempt-123",
            criterion="test_api_response_format",
            evidence_refs=["test_output.log", "error.txt"],
            hints=["test_failure_hint"],
        )
        assert packet.failure_class == FailureClass.RETRYABLE
        assert packet.attempt_id == "task-1-attempt-123"
        assert packet.task_id == "task-1"
        assert packet.criterion == "test_api_response_format"
        assert len(packet.evidence_refs) == 2
        assert packet.signature

    def test_minimal_packet(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.NEEDS_USER_INPUT,
            attempt_id="attempt-456",
        )
        assert packet.criterion is None
        assert packet.recommended_next_roles == ["user"]

    def test_attempt_id_required(self):
        with pytest.raises(ValueError, match="attempt_id is required"):
            FailureEvidencePacket(
                failure_class=FailureClass.RETRYABLE,
                attempt_id="",
            )

    def test_all_failure_classes_defined(self):
        expected = {
            "retryable",
            "needs_user_input",
            "stuck_or_repeating",
            "terminal_nonrecoverable",
        }
        assert {fc.value for fc in FailureClass} == expected

    def test_to_next_action_input(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-123",
            criterion="test_criterion",
            evidence_refs=["log.txt"],
            root_cause_hypothesis="missing return statement",
            prior_attempts=["attempt-001", "attempt-002"],
            hints=["test_failure_hint", "dependency_hint"],
            repeated_failure=True,
        )
        result = packet.to_next_action_input()
        assert result["failure_class"] == FailureClass.RETRYABLE
        assert result["attempt_id"] == "attempt-123"
        assert result["criterion"] == "test_criterion"
        assert result["evidence_refs"] == ["log.txt"]
        assert result["reproducible"] is True
        assert result["prior_attempts"] == ["attempt-001", "attempt-002"]
        assert result["root_cause_known"] is True
        assert result["repeated_failure"] is True
        assert "signature" in result
        assert result["recommended_next_roles"] == ["builder"]

    def test_to_next_action_input_no_root_cause(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-789",
            hints=["environment_hint"],
        )
        assert packet.to_next_action_input()["root_cause_known"] is False

    def test_reproducible_defaults_true(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.STUCK_OR_REPEATING,
            attempt_id="attempt-000",
        )
        assert packet.reproducible is True

    def test_prior_attempts_defaults_empty(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.TERMINAL_NONRECOVERABLE,
            attempt_id="attempt-111",
        )
        assert packet.prior_attempts == []

    def test_signature_includes_key_failure_dimensions(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.RETRYABLE,
            attempt_id="attempt-1",
            criterion="tests::unit",
            failing_command="pytest -q",
            missing_artifacts=["src/foo.py"],
            recent_lane="repair",
            hints=["test_failure_hint"],
        )
        assert "pytest -q" in packet.signature
        assert "src/foo.py" in packet.signature
        assert "test_failure_hint" in packet.signature

    def test_to_dict_serializes_enriched_contract(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.STUCK_OR_REPEATING,
            attempt_id="attempt-2",
            human_summary="same failure repeated after shallow fixes",
            machine_action="force_strategy_shift",
            recommended_next_roles=["debugger"],
            hints=["dependency_hint"],
            repeated_failure=True,
        )
        data = packet.to_dict()
        assert data["human_summary"] == "same failure repeated after shallow fixes"
        assert data["machine_action"] == "force_strategy_shift"
        assert data["recommended_next_roles"] == ["debugger"]
        assert data["hints"] == ["dependency_hint"]
        assert data["repeated_failure"] is True
