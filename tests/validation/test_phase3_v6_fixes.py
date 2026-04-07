"""Phase 3 v6 adversarial fixes: structural types + created_at binding."""

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
# Fix 1: Structural type enforcement — non-dict list items rejected
# ─────────────────────────────────────────────────────────────────

class TestStructuralTypes:
    def test_list_item_in_artifact_refs_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "artifact_refs": [["secret"]],  # list instead of dict
        }
        with pytest.raises(ValueError, match="must be a dict"):
            ReviewerInput.from_raw(raw)
    
    def test_list_item_in_criteria_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [["secret"]],  # list instead of dict
        }
        with pytest.raises(ValueError, match="must be a dict"):
            ReviewerInput.from_raw(raw)
    
    def test_validation_verdict_as_list_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "validation_verdict": [{"builder_rationale": "secret"}],
        }
        with pytest.raises(ValueError, match="must be a dict"):
            ReviewerInput.from_raw(raw)
    
    def test_non_string_spec_rejected(self):
        raw = {"spec": {"hidden": "data"}, "criteria": []}
        with pytest.raises(ValueError, match="spec must be str"):
            ReviewerInput.from_raw(raw)
    
    def test_non_list_artifact_refs_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [],
            "artifact_refs": {"sneaky": "dict"},
        }
        with pytest.raises(ValueError, match="must be a list"):
            ReviewerInput.from_raw(raw)
    
    def test_nested_dict_in_triple_field_rejected(self):
        raw = {
            "spec": "x",
            "criteria": [{
                "criterion_id": "c1",
                "description": "test",
                "criterion_class": "must_pass",
                "triple": {
                    "build_target": {"hidden": "framing"},  # must be str
                    "verification_command": "y",
                    "expected_output": "z",
                    "failure_signature": "",
                },
            }],
        }
        with pytest.raises(ValueError, match="must be str"):
            ReviewerInput.from_raw(raw)


# ─────────────────────────────────────────────────────────────────
# Fix 2: created_at bound in fingerprint
# ─────────────────────────────────────────────────────────────────

class TestCreatedAtBinding:
    def test_created_at_variation_rejected(self, tmp_path):
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
        # After record_run, art_real.producer_run_id is set by the registry
        original_created = art_real.created_at
        
        # Attack: same everything but different created_at
        art_attack = ArtifactRef(
            artifact_id=art_real.artifact_id,
            type=ArtifactType.LOG,
            path=art_real.path,
            content_hash=art_real.content_hash,
            producer_run_id=art_real.producer_run_id,
            created_at=original_created + 1000.0,  # different
            immutable=art_real.immutable,
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
    
    def test_exact_match_still_accepted(self, tmp_path):
        """Control: legitimate exact-match artifact should still pass."""
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
        # registry stamps art.producer_run_id = record.run_id
        
        result = CriterionResult(
            criterion_id="c1",
            verdict=CriterionVerdict.PASS,
            evidence_artifacts=[art],
            executed_command=cmd,
            run_id=record.run_id,
        )
        
        verdict = validator.validate("t1", [criterion], [result])
        assert verdict.status == TaskCompletionStatus.COMPLETE
