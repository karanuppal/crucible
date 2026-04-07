"""Phase 3 v5 adversarial fixes: reviewer scalar typing + full fingerprint binding."""

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
# Fix 1: Reviewer artifact_refs scalar type enforcement
# ─────────────────────────────────────────────────────────────────

class TestArtifactRefScalarTyping:
    def test_nested_dict_in_path_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "artifact_refs": [{
                "artifact_id": "a1",
                "type": "log",
                "path": {"builder_rationale": "secret"},  # should be str
                "content_hash": "xx",
                "producer_run_id": "r1",
                "created_at": 0.0,
            }],
        }
        with pytest.raises(ValueError, match="must be"):
            ReviewerInput.from_raw(raw)
    
    def test_list_in_content_hash_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "artifact_refs": [{
                "artifact_id": "a1",
                "type": "log",
                "path": "/tmp/x",
                "content_hash": ["a", "b"],
                "producer_run_id": "r1",
                "created_at": 0.0,
            }],
        }
        with pytest.raises(ValueError, match="must be"):
            ReviewerInput.from_raw(raw)
    
    def test_dict_in_type_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "artifact_refs": [{
                "artifact_id": "a1",
                "type": {"hidden": "rationale"},
                "path": "/tmp/x",
                "content_hash": "xx",
                "producer_run_id": "r1",
                "created_at": 0.0,
            }],
        }
        with pytest.raises(ValueError, match="must be"):
            ReviewerInput.from_raw(raw)
    
    def test_non_bool_immutable_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "artifact_refs": [{
                "artifact_id": "a1",
                "type": "log",
                "path": "/tmp/x",
                "content_hash": "xx",
                "producer_run_id": "r1",
                "created_at": 0.0,
                "immutable": "yes",  # should be bool
            }],
        }
        with pytest.raises(ValueError, match="must be"):
            ReviewerInput.from_raw(raw)


# ─────────────────────────────────────────────────────────────────
# Fix 2: Registry binds full fingerprint (path + type + immutable)
# ─────────────────────────────────────────────────────────────────

class TestFullFingerprintBinding:
    def test_same_id_same_hash_different_path_rejected(self, tmp_path):
        """Attack: submit artifact with same id+hash but different path."""
        registry_path = str(tmp_path / "registry.json")
        registry = RunRegistry(registry_path)
        validator = Validator(run_registry=registry)
        
        cmd = "pytest tests/foo.py"
        criterion = _mk_criterion(cmd=cmd)
        
        # Two files with IDENTICAL content (same hash)
        p_a = tmp_path / "original.log"
        p_a.write_text("PASSED")
        p_b = tmp_path / "decoy.log"
        p_b.write_text("PASSED")  # same content, same hash
        
        art_real = create_artifact_ref(str(p_a), ArtifactType.LOG, "placeholder")
        
        record = registry.record_run(
            command=cmd,
            exit_code=0,
            stdout="",
            stderr="",
            started_at=time.time(),
            finished_at=time.time(),
            artifacts=[art_real],
        )
        
        # Attack: same id, same hash, DIFFERENT path
        art_attack = ArtifactRef(
            artifact_id=art_real.artifact_id,
            type=ArtifactType.LOG,
            path=str(p_b),  # different path
            content_hash=art_real.content_hash,  # same hash (files identical)
            producer_run_id=record.run_id,
            created_at=time.time(),
        )
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art_attack],
            executed_command=cmd,
            run_id=record.run_id,
        )
        
        verdict = validator.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
    
    def test_same_id_same_hash_different_type_rejected(self, tmp_path):
        """Attack: change artifact type while keeping id+hash+path."""
        registry_path = str(tmp_path / "registry.json")
        registry = RunRegistry(registry_path)
        validator = Validator(run_registry=registry)
        
        cmd = "pytest tests/foo.py"
        criterion = _mk_criterion(cmd=cmd)
        
        p = tmp_path / "out.log"
        p.write_text("PASSED")
        art_real = create_artifact_ref(str(p), ArtifactType.LOG, "placeholder")
        
        record = registry.record_run(
            command=cmd,
            exit_code=0,
            stdout="",
            stderr="",
            started_at=time.time(),
            finished_at=time.time(),
            artifacts=[art_real],
        )
        
        # Attack: change type to something else
        art_attack = ArtifactRef(
            artifact_id=art_real.artifact_id,
            type=ArtifactType.REVIEWER_REPORT,  # different type
            path=art_real.path,
            content_hash=art_real.content_hash,
            producer_run_id=record.run_id,
            created_at=time.time(),
        )
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art_attack],
            executed_command=cmd,
            run_id=record.run_id,
        )
        
        verdict = validator.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
    
    def test_same_id_same_hash_different_immutable_rejected(self, tmp_path):
        registry_path = str(tmp_path / "registry.json")
        registry = RunRegistry(registry_path)
        validator = Validator(run_registry=registry)
        
        cmd = "pytest tests/foo.py"
        criterion = _mk_criterion(cmd=cmd)
        
        p = tmp_path / "out.log"
        p.write_text("PASSED")
        art_real = create_artifact_ref(str(p), ArtifactType.LOG, "placeholder")
        # art_real.immutable defaults to True
        
        record = registry.record_run(
            command=cmd,
            exit_code=0,
            stdout="",
            stderr="",
            started_at=time.time(),
            finished_at=time.time(),
            artifacts=[art_real],
        )
        
        # Attack: flip immutable flag
        art_attack = ArtifactRef(
            artifact_id=art_real.artifact_id,
            type=ArtifactType.LOG,
            path=art_real.path,
            content_hash=art_real.content_hash,
            producer_run_id=record.run_id,
            created_at=time.time(),
            immutable=False,  # flipped
        )
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art_attack],
            executed_command=cmd,
            run_id=record.run_id,
        )
        
        verdict = validator.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.INCOMPLETE
    
    def test_exact_match_still_passes(self, tmp_path):
        """Control: exact-match artifact still passes."""
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
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            executed_command=cmd,
            run_id=record.run_id,
        )
        
        verdict = validator.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.COMPLETE
