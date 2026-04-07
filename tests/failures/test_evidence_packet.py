"""Tests for failure evidence packet."""

import pytest

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket


class TestFailureEvidencePacket:
    def test_valid_packet_creation(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="task-1-attempt-123",
            criterion="test_api_response_format",
            evidence_refs=["test_output.log", "error.txt"],
        )
        assert packet.failure_class == FailureClass.VALIDATION_FAILURE
        assert packet.attempt_id == "task-1-attempt-123"
        assert packet.task_id == "task-1"
        assert packet.criterion == "test_api_response_format"
        assert len(packet.evidence_refs) == 2
        assert packet.signature

    def test_validation_failure_requires_criterion(self):
        with pytest.raises(ValueError, match="requires criterion"):
            FailureEvidencePacket(
                failure_class=FailureClass.VALIDATION_FAILURE,
                attempt_id="attempt-123",
            )

    def test_minimal_packet(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.AMBIGUITY_BLOCK,
            attempt_id="attempt-456",
        )
        assert packet.criterion is None
        assert packet.recommended_next_roles == ["user"]

    def test_attempt_id_required(self):
        with pytest.raises(ValueError, match="attempt_id is required"):
            FailureEvidencePacket(
                failure_class=FailureClass.VALIDATION_FAILURE,
                attempt_id="",
                criterion="test_criterion",
            )

    def test_all_failure_classes_defined(self):
        expected = {
            "ambiguity_block",
            "environment_block",
            "missing_dependency",
            "architecture_mismatch",
            "model_limitation",
            "validation_failure",
            "integration_conflict",
            "loop_detected",
        }
        assert {fc.value for fc in FailureClass} == expected

    def test_to_next_action_input(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="attempt-123",
            criterion="test_criterion",
            evidence_refs=["log.txt"],
            root_cause_hypothesis="missing return statement",
            prior_attempts=["attempt-001", "attempt-002"],
        )
        result = packet.to_next_action_input()
        assert result["failure_class"] == FailureClass.VALIDATION_FAILURE
        assert result["attempt_id"] == "attempt-123"
        assert result["criterion"] == "test_criterion"
        assert result["evidence_refs"] == ["log.txt"]
        assert result["reproducible"] is True
        assert result["prior_attempts"] == ["attempt-001", "attempt-002"]
        assert result["root_cause_known"] is True
        assert "signature" in result
        assert result["recommended_next_roles"] == ["builder"]

    def test_to_next_action_input_no_root_cause(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.ENVIRONMENT_BLOCK,
            attempt_id="attempt-789",
        )
        assert packet.to_next_action_input()["root_cause_known"] is False

    def test_reproducible_defaults_true(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.LOOP_DETECTED,
            attempt_id="attempt-000",
        )
        assert packet.reproducible is True

    def test_prior_attempts_defaults_empty(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.ARCHITECTURE_MISMATCH,
            attempt_id="attempt-111",
        )
        assert packet.prior_attempts == []

    def test_signature_includes_key_failure_dimensions(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id="attempt-1",
            criterion="tests::unit",
            failing_command="pytest -q",
            missing_artifacts=["src/foo.py"],
            recent_lane="repair",
        )
        assert "pytest -q" in packet.signature
        assert "src/foo.py" in packet.signature

    def test_to_dict_serializes_enriched_contract(self):
        packet = FailureEvidencePacket(
            failure_class=FailureClass.INTEGRATION_CONFLICT,
            attempt_id="attempt-2",
            human_summary="merge conflict after fan-in",
            machine_action="schedule_integration",
            recommended_next_roles=["integrator"],
        )
        data = packet.to_dict()
        assert data["human_summary"] == "merge conflict after fan-in"
        assert data["machine_action"] == "schedule_integration"
        assert data["recommended_next_roles"] == ["integrator"]
