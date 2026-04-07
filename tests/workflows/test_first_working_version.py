"""Phase 5 tests: first-working-version gate."""

import os
import pytest

from agentic_harness.workflows.first_working_version import (
    check_first_working_version, FirstWorkingVersionResult,
    FirstWorkingVersionError,
)


class TestGate:
    def test_scaffold_only_fails(self, tmp_path):
        """Empty scaffold with no real tests must fail the gate."""
        # Just create empty dirs/files — no actual tests
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_empty.py").write_text("# no actual tests\n")
        
        # Use a fake test command that succeeds with no tests
        result = check_first_working_version(
            str(tmp_path),
            test_command=["echo", "no tests collected"],
        )
        # No tests passed → not working
        assert not result.is_working
    
    def test_passing_tests_succeed(self, tmp_path):
        """A directory where tests actually pass should succeed."""
        # Use a stub command that mimics pytest output for 1 passed
        script = tmp_path / "fake_pytest.sh"
        script.write_text("#!/bin/bash\necho '1 passed in 0.01s'\nexit 0\n")
        script.chmod(0o755)
        
        result = check_first_working_version(
            str(tmp_path),
            test_command=[str(script)],
        )
        assert result.is_working
        assert result.passed_count == 1
    
    def test_failing_tests_fail_gate(self, tmp_path):
        script = tmp_path / "fake_pytest.sh"
        script.write_text("#!/bin/bash\necho '0 passed, 2 failed in 0.01s'\nexit 1\n")
        script.chmod(0o755)
        
        result = check_first_working_version(
            str(tmp_path),
            test_command=[str(script)],
        )
        assert not result.is_working
    
    def test_proof_artifact_created(self, tmp_path):
        script = tmp_path / "fake.sh"
        script.write_text("#!/bin/bash\necho '1 passed in 0.01s'\nexit 0\n")
        script.chmod(0o755)
        
        result = check_first_working_version(
            str(tmp_path),
            test_command=[str(script)],
        )
        assert os.path.isfile(result.proof_artifact_path)
        with open(result.proof_artifact_path) as f:
            content = f.read()
        assert "1 passed" in content
    
    def test_missing_command_fails(self, tmp_path):
        result = check_first_working_version(
            str(tmp_path),
            test_command=["/totally/nonexistent/binary"],
        )
        assert not result.is_working
    
    def test_missing_project_dir_raises(self):
        with pytest.raises(FirstWorkingVersionError):
            check_first_working_version("/nonexistent/path/xyz")
