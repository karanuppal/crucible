"""Phase 1 adversarial tests: malformed nested state, type validation."""

import json
import pytest

from agentic_harness.state.models import (
    ValidationState, RunState, serialize, deserialize,
)


class TestMalformedNestedState:
    """Malformed nested objects must be rejected, not silently accepted."""

    def test_criterion_result_wrong_bool_type(self):
        """passed='yes' instead of bool should be rejected."""
        data = {
            "validationId": "v1",
            "taskId": "t1",
            "criterionResults": [
                {"criterionId": "c1", "passed": "yes", "evidence": "x"}
            ],
            "gateResults": [],
            "artifactRefs": [],
            "verdict": "fail",
        }
        with pytest.raises(ValueError, match="must be bool"):
            deserialize("ValidationState", json.dumps(data))

    def test_gate_result_wrong_bool_types(self):
        data = {
            "validationId": "v1",
            "taskId": "t1",
            "criterionResults": [],
            "gateResults": [
                {"gateName": "g", "passed": "no", "mustPass": "sure"}
            ],
            "artifactRefs": [],
            "verdict": "fail",
        }
        with pytest.raises(ValueError, match="must be bool"):
            deserialize("ValidationState", json.dumps(data))

    def test_blocking_children_wrong_type(self):
        """blockingChildren='notalist' should be rejected."""
        data = {
            "runId": "r1", "projectId": "p1", "buildId": "b1",
            "taskId": "t1", "parentRunId": "", "role": "builder",
            "backend": "openclaw", "model": "opus", "cwd": "/tmp",
            "worktreeRef": "main", "blockingChildren": "notalist",
        }
        with pytest.raises(ValueError, match="must be a list"):
            deserialize("RunState", json.dumps(data))

    def test_criterion_result_missing_required(self):
        data = {
            "validationId": "v1",
            "taskId": "t1",
            "criterionResults": [
                {"criterionId": "c1"}  # missing passed and evidence
            ],
            "gateResults": [],
            "artifactRefs": [],
            "verdict": "fail",
        }
        with pytest.raises(ValueError, match="missing required fields"):
            deserialize("ValidationState", json.dumps(data))
