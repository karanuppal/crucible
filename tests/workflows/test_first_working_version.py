"""Phase 5 tests: first-working-version gate."""

import os
import pytest

from agentic_harness.workflows.first_working_version import (
    check_first_working_version, FirstWorkingVersionResult,
    FirstWorkingVersionError,
)


class TestGate:
    def test_scaffold_only_with_no_test_files_fails(self, tmp_path):
        """Empty scaffold with NO test files must fail (anti-forgery)."""
        result = check_first_working_version(
            str(tmp_path),
            test_command=["echo", "1 passed"],
        )
        assert not result.is_working
        assert "test files" in result.error.lower()
    
    def test_forged_output_with_no_real_tests_fails(self, tmp_path):
        """A script printing '1 passed' without real test files must fail."""
        script = tmp_path / "fake.sh"
        script.write_text("#!/bin/bash\necho '1 passed in 0.01s'\nexit 0\n")
        script.chmod(0o755)
        
        result = check_first_working_version(
            str(tmp_path),
            test_command=[str(script)],
        )
        # Even though command would print 1 passed, no real test files exist
        assert not result.is_working
    
    def test_passing_tests_with_real_files_succeed(self, tmp_path):
        """A directory with real test files where tests pass should succeed."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_real.py").write_text("def test_x(): pass\n")
        
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
        (tmp_path / "test_x.py").write_text("def test_x(): assert False\n")
        script = tmp_path / "fake_pytest.sh"
        script.write_text("#!/bin/bash\necho '0 passed, 2 failed in 0.01s'\nexit 1\n")
        script.chmod(0o755)
        
        result = check_first_working_version(
            str(tmp_path),
            test_command=[str(script)],
        )
        assert not result.is_working
    
    def test_proof_artifact_created(self, tmp_path):
        (tmp_path / "test_x.py").write_text("def test_x(): pass\n")
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
