"""Phase 3 v4 adversarial fixes: artifact_refs allowlist + registry hash binding."""

import time
import pytest

from crucible.validation.artifact import (
    ArtifactRef, ArtifactType, create_artifact_ref,
)
from crucible.validation.criterion import (
    Criterion, CriterionClass, CriterionResult, CriterionVerdict, VerificationTriple,
)
from crucible.validation.validator import Validator, TaskCompletionStatus
from crucible.validation.run_registry import RunRegistry
from crucible.validation.reviewer import ReviewerInput


def _mk_criterion(cmd="pytest tests/foo.py"):
    return Criterion(
        criterion_id="c1",
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
# Fix 1: artifact_refs payload must also be allowlisted
# ─────────────────────────────────────────────────────────────────

class TestArtifactRefsAllowlist:
    def test_forbidden_key_in_artifact_ref_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "artifact_refs": [
                {
                    "artifact_id": "a1",
                    "type": "log",
                    "path": "/tmp/x",
                    "content_hash": "xx",
                    "producer_run_id": "r1",
                    "created_at": 0.0,
                    "builder_rationale": "hidden framing",  # forbidden
                }
            ],
        }
        with pytest.raises(ValueError, match="forbidden|disallowed"):
            ReviewerInput.from_raw(raw)
    
    def test_unknown_key_in_artifact_ref_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "artifact_refs": [
                {
                    "artifact_id": "a1",
                    "type": "log",
                    "path": "/tmp/x",
                    "content_hash": "xx",
                    "producer_run_id": "r1",
                    "created_at": 0.0,
                    "secret_backchannel": "builder context",  # not allowed
                }
            ],
        }
        with pytest.raises(ValueError, match="disallowed"):
            ReviewerInput.from_raw(raw)
    
    def test_clean_artifact_ref_accepted(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "artifact_refs": [
                {
                    "artifact_id": "a1",
                    "type": "log",
                    "path": "/tmp/x",
                    "content_hash": "xx",
                    "producer_run_id": "r1",
                    "created_at": 0.0,
                    "immutable": True,
                }
            ],
        }
        ReviewerInput.from_raw(raw)  # should not raise
    
    def test_diffs_must_be_string(self):
        """diffs with nested dict should be rejected."""
        raw = {
            "spec": "x",
            "criteria": [],
            "diffs": {"builder_framing": "smuggled"},  # must be string
        }
        with pytest.raises(ValueError, match="must be a string"):
            ReviewerInput.from_raw(raw)


# ─────────────────────────────────────────────────────────────────
# Fix 2: Registry must bind artifact hash, not just ID
# ─────────────────────────────────────────────────────────────────

class TestRegistryHashBinding:
    def test_substituted_artifact_with_same_id_rejected(self, tmp_path):
        """Attack: register run with artifact A, then submit different artifact B with same ID."""
        registry_path = str(tmp_path / "registry.json")
        registry = RunRegistry(registry_path)
        validator = Validator(run_registry=registry)
        
        cmd = "pytest tests/foo.py"
        criterion = _mk_criterion(cmd=cmd)
        
        # Artifact A: real passing evidence
        p_good = tmp_path / "good.log"
        p_good.write_text("PASSED")
        art_a = create_artifact_ref(str(p_good), ArtifactType.LOG, "placeholder")
        
        # Register run with artifact A
        record = registry.record_run(
            command=cmd,
            exit_code=0,
            stdout="PASSED",
            stderr="",
            started_at=time.time(),
            finished_at=time.time(),
            artifacts=[art_a],
        )
        
        # Attack: fake artifact B with same artifact_id but different content
        p_bad = tmp_path / "bad.log"
        p_bad.write_text("FAKE CONTENT")
        from crucible.validation.artifact import compute_file_hash
        art_b = ArtifactRef(
            artifact_id=art_a.artifact_id,  # collision
            type=ArtifactType.LOG,
            path=str(p_bad),
            content_hash=compute_file_hash(str(p_bad)),  # different hash
            producer_run_id=record.run_id,
            created_at=time.time(),
        )
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art_b],  # forged
            executed_command=cmd,
            run_id=record.run_id,
        )
        
        verdict = validator.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
    
    def test_legitimate_artifact_still_accepted(self, tmp_path):
        """Control: the real artifact should still pass."""
        registry_path = str(tmp_path / "registry.json")
        registry = RunRegistry(registry_path)
        validator = Validator(run_registry=registry)
        
        cmd = "pytest tests/foo.py"
        criterion = _mk_criterion(cmd=cmd)
        
        p = tmp_path / "real.log"
        p.write_text("PASSED")
        art = create_artifact_ref(str(p), ArtifactType.LOG, "placeholder")
        
        record = registry.record_run(
            command=cmd,
            exit_code=0,
            stdout="PASSED",
            stderr="",
            started_at=time.time(),
            finished_at=time.time(),
            artifacts=[art],
        )
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
    
    def test_tampered_after_registration_rejected(self, tmp_path):
        """If the file is modified after registration, provenance fails."""
        registry_path = str(tmp_path / "registry.json")
        registry = RunRegistry(registry_path)
        validator = Validator(run_registry=registry)
        
        cmd = "pytest tests/foo.py"
        criterion = _mk_criterion(cmd=cmd)
        
        p = tmp_path / "out.log"
        p.write_text("PASSED")
        art = create_artifact_ref(str(p), ArtifactType.LOG, "placeholder")
        
        record = registry.record_run(
            command=cmd,
            exit_code=0,
            stdout="",
            stderr="",
            started_at=time.time(),
            finished_at=time.time(),
            artifacts=[art],
        )
        art.producer_run_id = record.run_id
        
        # Tamper
        p.write_text("TAMPERED")
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            executed_command=cmd,
            run_id=record.run_id,
        )
        
        verdict = validator.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
