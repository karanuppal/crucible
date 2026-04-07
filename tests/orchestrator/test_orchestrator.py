"""Phase 7 tests: top-level orchestrator end-to-end."""

import pytest

from agentic_harness.orchestrator.orchestrator import (
    Orchestrator, OrchestratorPhase, TaskDefinition,
)
from agentic_harness.validation.criterion import (
    Criterion, CriterionClass, VerificationTriple,
)
from agentic_harness.runner.run_graph import RunRole
from agentic_harness.ambiguity.gate import (
    AmbiguityFinding, AmbiguityCategory,
)
from agentic_harness.accelerators.capabilities import (
    BackendCapabilities, BackendCapabilityMatrix, Capability,
)
from agentic_harness.accelerators.adapters import (
    InMemoryAdapter, AdapterStatus,
)
from agentic_harness.accelerators.router import Router


def _make_router(outcome=AdapterStatus.COMPLETE):
    matrix = BackendCapabilityMatrix()
    caps = BackendCapabilities(
        backend_id="test",
        supports={
            Capability.SHELL_EXEC,
            Capability.ARTIFACT_PRODUCTION,
            Capability.FILE_WRITE,
        },
    )
    matrix.register(caps)
    adapters = {
        "test": InMemoryAdapter("test", caps, simulated_runtime_s=0.001, simulated_outcome=outcome),
    }
    return Router(matrix, adapters, preferred_order=["test"])


def _make_task(task_id="t1", cmd="pytest -k test_x"):
    return TaskDefinition(
        task_id=task_id,
        description="implement x",
        criteria=[Criterion(
            criterion_id=f"c-{task_id}",
            description="x works",
            criterion_class=CriterionClass.MUST_PASS,
            triple=VerificationTriple(
                build_target="src/x.py",
                verification_command=cmd,
                expected_output="PASSED",
                failure_signature="FAILED",
            ),
        )],
        spec_command=cmd,
        intensity_hint="S",
    )


def _make_orchestrator(tmp_path, router=None):
    if router is None:
        router = _make_router()
    return Orchestrator(
        project_id="proj-1",
        build_id="build-1",
        ledger_path=str(tmp_path / "ledger.jsonl"),
        memory_path=str(tmp_path / "mem.json"),
        registry_path=str(tmp_path / "registry.json"),
        router=router,
    )


class TestHappyPath:
    def test_full_loop_completes_with_real_evidence(self, tmp_path):
        """When backend reports COMPLETE, orchestrator should produce real
        evidence and validate to completion."""
        orch = _make_orchestrator(tmp_path)
        tasks = [_make_task("t1"), _make_task("t2")]
        
        state = orch.run_build("test spec", tasks)
        
        assert state.current_phase == OrchestratorPhase.DONE
        assert "t1" in state.completed_tasks
        assert "t2" in state.completed_tasks
        assert state.failed_tasks == []
    
    def test_phase_transitions_recorded(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        tasks = [_make_task()]
        
        state = orch.run_build("spec", tasks)
        assert state.current_phase == OrchestratorPhase.DONE


class TestAmbiguityGate:
    def test_blocks_on_high_severity(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        findings = [
            AmbiguityFinding(
                category=AmbiguityCategory.MISSING_CRITERIA,
                description="no acceptance criteria",
                severity="high",
            ),
        ]
        state = orch.run_build("spec", [_make_task()], ambiguity_findings=findings)
        
        assert state.current_phase == OrchestratorPhase.BLOCKED
        assert "Ambiguity gate" in state.blocked_reason
    
    def test_proceeds_on_no_findings(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        state = orch.run_build("spec", [_make_task()], ambiguity_findings=[])
        # Not blocked by ambiguity
        assert "Ambiguity gate" not in (state.blocked_reason or "")


class TestFailureHandling:
    def test_failed_runs_recorded(self, tmp_path):
        # Use FAILED outcome from backend
        router = _make_router(outcome=AdapterStatus.FAILED)
        orch = _make_orchestrator(tmp_path, router=router)
        tasks = [_make_task("t1")]
        
        state = orch.run_build("spec", tasks)
        # Either blocked or has failed tasks
        assert "t1" in state.failed_tasks or state.current_phase == OrchestratorPhase.BLOCKED


class TestLedgerEvents:
    def test_spec_created_event_emitted(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        orch.run_build("spec", [_make_task()])
        
        # Check ledger has events
        from agentic_harness.ledger.ledger import Ledger
        ledger = Ledger(str(tmp_path / "ledger.jsonl"))
        assert ledger.count > 0
    
    def test_task_created_events_emitted(self, tmp_path):
        from agentic_harness.ledger.ledger import EventType, Ledger
        
        orch = _make_orchestrator(tmp_path)
        orch.run_build("spec", [_make_task("t1"), _make_task("t2")])
        
        ledger = Ledger(str(tmp_path / "ledger.jsonl"))
        task_events = ledger.events_by_type(EventType.TASK_CREATED)
        assert len(task_events) == 2
