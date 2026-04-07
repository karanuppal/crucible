"""Phase 8 tests: TaskDefinition preflight validator."""

import pytest

from crucible.runtime.preflight import lint_plan, LintSeverity


def _good_plan():
    return {
        "spec": "build a thing",
        "project_id": "p1",
        "build_id": "b1",
        "tasks": [
            {
                "task_id": "implement-foo",
                "description": "implement src/foo.py with tests in tests/test_foo.py",
                "criteria": [
                    {
                        "criterion_id": "c1",
                        "criterion_class": "must_pass",
                        "triple": {
                            "build_target": "src/foo.py",
                            "verification_command": "pytest tests/test_foo.py",
                            "expected_output": "PASSED",
                            "failure_signature": "FAILED",
                        },
                    }
                ],
                "role": "builder",
                "intensity_hint": "S",
            }
        ],
    }


class TestStructural:
    def test_valid_plan_passes(self):
        result = lint_plan(_good_plan())
        assert result.valid, f"errors: {[f.code for f in result.errors()]}"
    
    def test_missing_top_level(self):
        result = lint_plan({"tasks": []})
        assert not result.valid
        codes = [f.code for f in result.errors()]
        assert "MISSING_TOP_LEVEL_FIELD" in codes
    
    def test_zero_tasks(self):
        plan = _good_plan()
        plan["tasks"] = []
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "ZERO_TASKS" for f in result.errors())
    
    def test_duplicate_task_id(self):
        plan = _good_plan()
        plan["tasks"].append(plan["tasks"][0].copy())
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "TASK_ID_DUPLICATE" for f in result.errors())
    
    def test_empty_description(self):
        plan = _good_plan()
        plan["tasks"][0]["description"] = ""
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "DESCRIPTION_EMPTY" for f in result.errors())
    
    def test_short_description(self):
        plan = _good_plan()
        plan["tasks"][0]["description"] = "do x"
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "DESCRIPTION_TOO_SHORT" for f in result.errors())
    
    def test_zero_criteria(self):
        plan = _good_plan()
        plan["tasks"][0]["criteria"] = []
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "ZERO_CRITERIA" for f in result.errors())
    
    def test_no_must_pass(self):
        plan = _good_plan()
        plan["tasks"][0]["criteria"][0]["criterion_class"] = "informational"
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "NO_MUST_PASS_CRITERIA" for f in result.errors())
    
    def test_invalid_role(self):
        plan = _good_plan()
        plan["tasks"][0]["role"] = "supreme-leader"
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "INVALID_ROLE" for f in result.errors())


class TestVagueLanguage:
    def test_vague_works_rejected(self):
        plan = _good_plan()
        plan["tasks"][0]["description"] = "make sure it works"
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "VAGUE_DESCRIPTION" for f in result.errors())
    
    def test_vague_properly_rejected(self):
        plan = _good_plan()
        plan["tasks"][0]["description"] = "ensure it runs properly"
        result = lint_plan(plan)
        assert not result.valid
    
    def test_vague_with_measurable_passes(self):
        """Vague tokens are OK when paired with measurable conditions."""
        plan = _good_plan()
        plan["tasks"][0]["description"] = "ensure src/foo.py works with tests/test_foo.py"
        result = lint_plan(plan)
        # 'works' but with measurable file refs → not flagged
        assert result.valid, f"unexpected errors: {[f.code for f in result.errors()]}"


class TestGenericTriples:
    def test_generic_build_target_rejected(self):
        plan = _good_plan()
        plan["tasks"][0]["criteria"][0]["triple"]["build_target"] = "project"
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "GENERIC_BUILD_TARGET" for f in result.errors())
    
    def test_generic_expected_output_rejected(self):
        plan = _good_plan()
        plan["tasks"][0]["criteria"][0]["triple"]["expected_output"] = "success"
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "GENERIC_EXPECTED_OUTPUT" for f in result.errors())
    
    def test_short_expected_output_rejected(self):
        plan = _good_plan()
        plan["tasks"][0]["criteria"][0]["triple"]["expected_output"] = "OK"
        result = lint_plan(plan)
        assert not result.valid
    
    def test_empty_triple_field_rejected(self):
        plan = _good_plan()
        plan["tasks"][0]["criteria"][0]["triple"]["build_target"] = ""
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "TRIPLE_FIELD_MISSING" for f in result.errors())
    
    def test_duplicate_triple_across_criteria(self):
        plan = _good_plan()
        # Add a second task with the same triple
        plan["tasks"].append({
            "task_id": "implement-bar",
            "description": "implement src/bar.py with tests/test_bar.py",
            "criteria": [{
                "criterion_id": "c1",
                "criterion_class": "must_pass",
                "triple": plan["tasks"][0]["criteria"][0]["triple"].copy(),
            }],
            "role": "builder",
            "intensity_hint": "S",
        })
        result = lint_plan(plan)
        assert not result.valid
        assert any(f.code == "DUPLICATE_TRIPLE_ACROSS_CRITERIA" for f in result.errors())


class TestNormalization:
    def test_normalized_plan_returned_on_success(self):
        plan = _good_plan()
        plan["tasks"][0]["task_id"] = "  implement-foo  "
        result = lint_plan(plan)
        assert result.valid
        assert result.normalized_plan is not None
        assert result.normalized_plan["tasks"][0]["task_id"] == "implement-foo"
    
    def test_no_normalized_plan_on_failure(self):
        result = lint_plan({"tasks": []})
        assert result.normalized_plan is None
