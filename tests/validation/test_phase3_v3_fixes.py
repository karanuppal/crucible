"""Phase 3 v3 adversarial fixes."""

import json
import time
import pytest

from agentic_harness.validation.artifact import (
    ArtifactRef, ArtifactType, create_artifact_ref,
)
from agentic_harness.validation.criterion import (
    Criterion, CriterionClass, CriterionResult, CriterionVerdict, VerificationTriple,
)
from agentic_harness.validation.validator import Validator, TaskCompletionStatus
from agentic_harness.validation.run_registry import RunRegistry
from agentic_harness.validation.reviewer import ReviewerInput
from agentic_harness.validation.ladder import LadderRung
from agentic_harness.validation.ladder_executor import (
    LadderExecutor, LadderExecutionState, save_ladder_state, load_ladder_state,
)


def _mk_criterion(cid="c1", cmd="pytest tests/foo.py", rung_marker=None):
    return Criterion(
        criterion_id=cid,
        description="x",
        criterion_class=CriterionClass.MUST_PASS,
        triple=VerificationTriple(
            build_target="src/foo.py",
            verification_command=cmd,
            expected_output="PASSED",
            failure_signature="FAILED",
        ),
    )


# ─────────────────────────────────────────────────────────────────
# Fix 1: Triple enforcement at validator boundary
# ─────────────────────────────────────────────────────────────────

class TestTripleEnforcement:
    def test_incomplete_triple_fails_closed(self):
        v = Validator()
        bad = Criterion(
            criterion_id="c1",
            description="x",
            criterion_class=CriterionClass.MUST_PASS,
            triple=VerificationTriple(
                build_target="",  # empty!
                verification_command="pytest",
                expected_output="ok",
            ),
        )
        verdict = v.validate("t1", [bad], [])
        assert verdict.status == TaskCompletionStatus.FAILED
        assert "incomplete verification triple" in verdict.reason
    
    def test_empty_command_triple_fails(self):
        v = Validator()
        bad = Criterion(
            criterion_id="c1",
            description="x",
            criterion_class=CriterionClass.MUST_PASS,
            triple=VerificationTriple(
                build_target="foo.py",
                verification_command="",
                expected_output="ok",
            ),
        )
        verdict = v.validate("t1", [bad], [])
        assert verdict.status == TaskCompletionStatus.FAILED


# ─────────────────────────────────────────────────────────────────
# Fix 2: Trusted run registry (provenance)
# ─────────────────────────────────────────────────────────────────

class TestRunRegistryProvenance:
    def test_unregistered_run_rejected(self, tmp_path):
        """Without a run in the registry, PASS gets downgraded."""
        registry_path = str(tmp_path / "registry.json")
        registry = RunRegistry(registry_path)
        validator = Validator(run_registry=registry)
        
        cmd = "pytest tests/foo.py"
        criterion = _mk_criterion("c1", cmd=cmd)
        
        p = tmp_path / "out.log"
        p.write_text("PASSED")
        art = create_artifact_ref(str(p), ArtifactType.LOG, "run-fake")
        
        # Caller claims these runs, but registry has no record
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            executed_command=cmd,
            run_id="run-fake",
        )
        
        verdict = validator.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
    
    def test_registered_run_accepted(self, tmp_path):
        registry_path = str(tmp_path / "registry.json")
        registry = RunRegistry(registry_path)
        validator = Validator(run_registry=registry)
        
        cmd = "pytest tests/foo.py"
        criterion = _mk_criterion("c1", cmd=cmd)
        
        p = tmp_path / "out.log"
        p.write_text("PASSED")
        
        # Create artifact FIRST to get its ID and hash
        art = create_artifact_ref(str(p), ArtifactType.LOG, "placeholder")
        
        # Record the run in registry, linking to the actual artifact (with hash)
        record = registry.record_run(
            command=cmd,
            exit_code=0,
            stdout="PASSED",
            stderr="",
            started_at=time.time(),
            finished_at=time.time(),
            artifacts=[art],
        )
        
        # Update the artifact's producer_run_id to match
        art.producer_run_id = record.run_id
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            executed_command=cmd,
            run_id=record.run_id,
        )
        
        verdict = validator.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.COMPLETE
    
    def test_registry_persistence(self, tmp_path):
        path = str(tmp_path / "registry.json")
        r1 = RunRegistry(path)
        record = r1.record_run(
            command="test",
            exit_code=0,
            stdout="ok",
            stderr="",
            started_at=1.0,
            finished_at=2.0,
            artifacts=[],
        )
        
        r2 = RunRegistry(path)
        assert r2.get(record.run_id) is not None
        assert r2.get(record.run_id).command == "test"


# ─────────────────────────────────────────────────────────────────
# Fix 3: Strict allowlist for reviewer input
# ─────────────────────────────────────────────────────────────────

class TestStrictAllowlist:
    def test_unknown_top_level_key_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "sneaky_context": "builder framing",  # not in allowlist
        }
        with pytest.raises(ValueError, match="disallowed keys"):
            ReviewerInput.from_raw(raw)
    
    def test_unknown_criterion_key_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [{
                "criterion_id": "c1",
                "description": "test",
                "criterion_class": "must_pass",
                "triple": {},
                "framing_notes": "builder context",  # not allowed
            }],
        }
        with pytest.raises(ValueError, match="disallowed keys"):
            ReviewerInput.from_raw(raw)
    
    def test_unknown_triple_key_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [{
                "criterion_id": "c1",
                "description": "test",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "x",
                    "verification_command": "y",
                    "expected_output": "z",
                    "builder_hint": "don't actually check this",  # not allowed
                },
            }],
        }
        with pytest.raises(ValueError, match="disallowed keys"):
            ReviewerInput.from_raw(raw)
    
    def test_clean_input_accepted(self):
        raw = {
            "spec": "x",
            "criteria": [{
                "criterion_id": "c1",
                "description": "test",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": "x",
                    "verification_command": "y",
                    "expected_output": "z",
                    "failure_signature": "FAIL",
                },
            }],
            "artifact_refs": [],
            "validation_verdict": {
                "task_id": "t1",
                "status": "complete",
                "must_pass_failures": [],
                "blocked_required": [],
                "reason": "ok",
                "criterion_results": [],
            },
            "diffs": "",
        }
        ReviewerInput.from_raw(raw)  # should not raise


# ─────────────────────────────────────────────────────────────────
# Fix 4: Ladder executor with persistence
# ─────────────────────────────────────────────────────────────────

class TestLadderExecutor:
    def test_runs_all_rungs_in_order(self):
        v = Validator()
        call_order = []
        
        def runner(rung, criteria):
            call_order.append(rung)
            # Return passing results for all criteria
            import tempfile
            results = []
            for c in criteria:
                # Create a real passing artifact
                import os
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
                tmp.write("PASSED")
                tmp.close()
                art = create_artifact_ref(tmp.name, ArtifactType.LOG, f"run-{rung.name}")
                results.append(CriterionResult(
                    criterion_id=c.criterion_id,
                    verdict=CriterionVerdict.PASS,
                    evidence_artifacts=[art],
                    executed_command=c.triple.verification_command,
                    run_id=f"run-{rung.name}",
                ))
            return results, f"transcript for {rung.name}"
        
        executor = LadderExecutor(v, runner)
        criteria_by_rung = {
            LadderRung.STATIC: [_mk_criterion("c1")],
            LadderRung.UNIT: [_mk_criterion("c2")],
            LadderRung.INTEGRATION: [_mk_criterion("c3")],
            LadderRung.END_TO_END: [_mk_criterion("c4")],
        }
        
        state = executor.execute("t1", criteria_by_rung)
        
        assert state.is_complete
        assert call_order == [LadderRung.STATIC, LadderRung.UNIT, LadderRung.INTEGRATION, LadderRung.END_TO_END]
        assert len(state.rung_results) == 4
    
    def test_fail_fast_stops_later_rungs(self):
        v = Validator()
        call_order = []
        
        def runner(rung, criteria):
            call_order.append(rung)
            # Fail at UNIT rung
            if rung == LadderRung.UNIT:
                return [CriterionResult(
                    criterion_id=criteria[0].criterion_id,
                    verdict=CriterionVerdict.FAIL,
                )], "unit failed"
            # Pass others
            import tempfile
            results = []
            for c in criteria:
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
                tmp.write("PASSED")
                tmp.close()
                art = create_artifact_ref(tmp.name, ArtifactType.LOG, f"run-{rung.name}")
                results.append(CriterionResult(
                    criterion_id=c.criterion_id,
                    verdict=CriterionVerdict.PASS,
                    evidence_artifacts=[art],
                    executed_command=c.triple.verification_command,
                    run_id=f"run-{rung.name}",
                ))
            return results, ""
        
        executor = LadderExecutor(v, runner)
        criteria_by_rung = {
            LadderRung.STATIC: [_mk_criterion("c1")],
            LadderRung.UNIT: [_mk_criterion("c2")],
            LadderRung.INTEGRATION: [_mk_criterion("c3")],
        }
        
        state = executor.execute("t1", criteria_by_rung)
        
        assert not state.is_complete
        assert state.last_failure_rung == LadderRung.UNIT
        # INTEGRATION should NOT have been called
        assert LadderRung.INTEGRATION not in call_order
    
    def test_state_persistence(self, tmp_path):
        state = LadderExecutionState(
            task_id="t1",
            completed_rungs=[LadderRung.STATIC, LadderRung.UNIT],
            last_failure_rung=LadderRung.UNIT,
            is_complete=False,
        )
        
        path = str(tmp_path / "ladder.json")
        save_ladder_state(state, path)
        
        loaded = load_ladder_state(path)
        assert loaded.task_id == "t1"
        assert LadderRung.STATIC in loaded.completed_rungs
        assert loaded.last_failure_rung == LadderRung.UNIT
        assert not loaded.is_complete
