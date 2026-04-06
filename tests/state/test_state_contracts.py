"""Phase 1 validation: State contract tests.

Validation matrix requirements:
- Roundtrip serialize/deserialize for minimal, normal, maximal examples (all 6 types)
- Reject missing required fields
- Reject wrong enum values
- Reject unknown keys in strict mode
- Persist → reload → verify exact equivalence
"""

import json
import pytest

from agentic_harness.state.models import (
    ProjectState, BuildState, TaskState, RunState, ValidationState, IntegrationState,
    ProjectMode, TaskSize, TaskStatus, RunStatus, RunRole, ValidationVerdict,
    IntegrationStatus, CleanupStatus, VerificationTriple, CriterionResult, GateResult,
    serialize, deserialize,
)


# --- Fixtures: minimal valid objects ---

def minimal_project() -> ProjectState:
    return ProjectState(
        projectId="proj-1",
        mode=ProjectMode.EXISTING,
        repoPath="/tmp/repo",
        remoteRepo="https://github.com/test/repo",
        activeBuildId="build-1",
        machineProfileRef="machine-1",
        ledgerRef="ledger-1",
        currentSpecRef="spec-1",
    )


def minimal_build() -> BuildState:
    return BuildState(buildId="build-1", projectId="proj-1", phase="decomposition", specRef="spec-1")


def minimal_task() -> TaskState:
    return TaskState(
        taskId="task-1",
        title="Implement feature X",
        description="Build the feature per spec",
        roleNeeded=RunRole.BUILDER,
        size=TaskSize.M,
    )


def maximal_task() -> TaskState:
    return TaskState(
        taskId="task-2",
        title="Complex task",
        description="Multi-file refactor",
        roleNeeded=RunRole.BUILDER,
        size=TaskSize.L,
        dependencies=["task-1"],
        allowedPaths=["src/", "tests/"],
        deliverables=["refactored module", "updated tests"],
        verificationTriple=VerificationTriple(
            whatToBuild="Refactored auth module",
            howToVerify="pytest tests/auth/ passes",
            whatFailureLooksLike="ImportError or test failures",
        ),
        status=TaskStatus.IN_PROGRESS,
        assignedRunIds=["run-1", "run-2"],
        rejections=[{"attempt": 1, "reason": "wrong approach"}],
        failureClass="validation_failure",
    )


def minimal_run() -> RunState:
    return RunState(
        runId="run-1",
        projectId="proj-1",
        buildId="build-1",
        taskId="task-1",
        parentRunId="",
        role=RunRole.BUILDER,
        backend="openclaw",
        model="opus-4.6",
        cwd="/tmp/repo",
        worktreeRef="main",
    )


def minimal_validation() -> ValidationState:
    return ValidationState(validationId="val-1", taskId="task-1")


def maximal_validation() -> ValidationState:
    return ValidationState(
        validationId="val-2",
        taskId="task-2",
        criterionResults=[
            CriterionResult(criterionId="c1", passed=True, evidence="tests pass", artifactRef="log-1"),
        ],
        gateResults=[
            GateResult(gateName="unit_tests", passed=True, mustPass=True, detail="24/24 passed"),
        ],
        artifactRefs=["log-1", "screenshot-1"],
        verdict=ValidationVerdict.PASS,
    )


def minimal_integration() -> IntegrationState:
    return IntegrationState(integrationId="int-1")


# --- Roundtrip Tests ---

class TestRoundtrip:
    """All 6 state types must survive JSON roundtrip."""

    @pytest.mark.parametrize("factory,type_name", [
        (minimal_project, "ProjectState"),
        (minimal_build, "BuildState"),
        (minimal_task, "TaskState"),
        (maximal_task, "TaskState"),
        (minimal_run, "RunState"),
        (minimal_validation, "ValidationState"),
        (maximal_validation, "ValidationState"),
        (minimal_integration, "IntegrationState"),
    ])
    def test_roundtrip(self, factory, type_name):
        original = factory()
        json_str = serialize(original)
        restored = deserialize(type_name, json_str)
        # Compare by re-serializing (handles enum normalization)
        assert serialize(original) == serialize(restored)

    def test_roundtrip_preserves_all_fields(self):
        task = maximal_task()
        json_str = serialize(task)
        data = json.loads(json_str)
        assert data["taskId"] == "task-2"
        assert data["verificationTriple"]["whatToBuild"] == "Refactored auth module"
        assert data["rejections"] == [{"attempt": 1, "reason": "wrong approach"}]


# --- Schema Rejection Tests ---

class TestSchemaRejection:
    """Missing required fields and wrong enums must be rejected."""

    def test_missing_required_field_project(self):
        data = {"projectId": "proj-1"}  # missing most required fields
        with pytest.raises(ValueError, match="Missing required fields"):
            deserialize("ProjectState", json.dumps(data))

    def test_missing_required_field_run(self):
        data = {"runId": "run-1", "projectId": "proj-1"}
        with pytest.raises(ValueError, match="Missing required fields"):
            deserialize("RunState", json.dumps(data))

    def test_wrong_enum_value_project_mode(self):
        proj = minimal_project()
        json_str = serialize(proj)
        data = json.loads(json_str)
        data["mode"] = "invalid_mode"
        with pytest.raises(ValueError, match="Invalid value for mode"):
            deserialize("ProjectState", json.dumps(data))

    def test_wrong_enum_value_run_status(self):
        run = minimal_run()
        json_str = serialize(run)
        data = json.loads(json_str)
        data["status"] = "exploded"
        with pytest.raises(ValueError, match="Invalid value for status"):
            deserialize("RunState", json.dumps(data))

    def test_unknown_keys_strict_mode(self):
        proj = minimal_project()
        json_str = serialize(proj)
        data = json.loads(json_str)
        data["hackerField"] = "surprise"
        with pytest.raises(ValueError, match="Unknown fields"):
            deserialize("ProjectState", json.dumps(data), strict=True)

    def test_unknown_keys_lenient_mode(self):
        proj = minimal_project()
        json_str = serialize(proj)
        data = json.loads(json_str)
        data["extraField"] = "ok"
        # Should not raise in lenient mode
        result = deserialize("ProjectState", json.dumps(data), strict=False)
        assert result.projectId == "proj-1"

    def test_unknown_state_type(self):
        with pytest.raises(ValueError, match="Unknown state type"):
            deserialize("FakeState", "{}")

    def test_non_object_json(self):
        with pytest.raises(ValueError, match="Expected JSON object"):
            deserialize("ProjectState", '"just a string"')

    def test_malformed_json(self):
        with pytest.raises(json.JSONDecodeError):
            deserialize("ProjectState", "not json at all{{{")
