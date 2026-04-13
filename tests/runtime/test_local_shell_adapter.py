"""G3: LocalShellAdapter must execute real commands and report honestly."""

import pytest

from crucible.accelerators.adapters import AdapterRunSpec, AdapterStatus
from crucible.accelerators.capabilities import Capability
from crucible.runtime.local_shell_adapter import LocalShellAdapter


def _spec(cmd, expected="", spec_id="s1", timeout=10, cwd="/tmp", metadata=None):
    payload = {"expected_output": expected}
    if metadata:
        payload.update(metadata)
    return AdapterRunSpec(
        spec_id=spec_id,
        prompt=cmd,
        cwd=cwd,
        timeout_seconds=timeout,
        required_capabilities={Capability.SHELL_EXEC},
        metadata=payload,
    )


class TestRealExecution:
    def test_executes_real_command(self):
        adapter = LocalShellAdapter()
        handle = adapter.spawn(_spec("echo hello"))
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.COMPLETE
        assert "exit_code: 0" in result.summary
    
    def test_captures_stdout_and_exit_code(self):
        adapter = LocalShellAdapter()
        handle = adapter.spawn(_spec("printf 'PASSED\\n'", expected="PASSED"))
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.COMPLETE
    
    def test_failing_command_marked_failed(self):
        adapter = LocalShellAdapter()
        handle = adapter.spawn(_spec("false"))
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.FAILED
        assert "exited 1" in result.error or "exit_code" in result.summary
    
    def test_nonexistent_command_marked_failed(self):
        adapter = LocalShellAdapter()
        handle = adapter.spawn(_spec("this-command-does-not-exist-12345"))
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.FAILED
        assert result.error  # some error message
    
    def test_command_succeeds_but_expected_missing_fails(self):
        """The reviewer's killer test: command exits 0 but produces wrong output."""
        adapter = LocalShellAdapter()
        handle = adapter.spawn(_spec("echo BAR", expected="FOO"))
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.FAILED
        assert "expected substring" in result.error.lower()
    
    def test_command_succeeds_and_expected_present_passes(self):
        adapter = LocalShellAdapter()
        handle = adapter.spawn(_spec("echo 'all tests PASSED here'", expected="PASSED"))
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.COMPLETE
    
    def test_timeout_marks_timed_out(self):
        adapter = LocalShellAdapter()
        handle = adapter.spawn(_spec("sleep 5", timeout=1))
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.TIMED_OUT
        assert "timed out" in result.error.lower()

    def test_python_virtualenv_bin_is_added_to_path(self, tmp_path):
        adapter = LocalShellAdapter()
        bin_dir = tmp_path / ".venv" / "bin"
        bin_dir.mkdir(parents=True)
        script = bin_dir / "hello-from-venv"
        script.write_text("#!/bin/sh\necho READY\n")
        script.chmod(0o755)
        handle = adapter.spawn(_spec(
            "hello-from-venv",
            expected="READY",
            cwd=str(tmp_path),
            metadata={"environment": {"strategy": {"environment_path": str(tmp_path / '.venv')}, "detected": {"ecosystem": "python"}}},
        ))
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.COMPLETE

    def test_metadata_command_overrides_prompt_for_task_aware_execution(self):
        adapter = LocalShellAdapter()
        handle = adapter.spawn(_spec(
            "Task: fix auth bug",
            expected="READY",
            metadata={"command": "printf 'READY\\n'"},
        ))
        result = adapter.collect(handle)
        assert result.status == AdapterStatus.COMPLETE
        assert "command: printf 'READY\\n'" in result.summary
    
    def test_capability_check_rejects_unsupported(self):
        adapter = LocalShellAdapter()
        spec = AdapterRunSpec(
            spec_id="s1", prompt="x", cwd="/tmp", timeout_seconds=1,
            required_capabilities={Capability.NETWORK},  # not declared
        )
        with pytest.raises(ValueError, match="not support"):
            adapter.spawn(spec)
    
    def test_collect_unknown_handle(self):
        from crucible.accelerators.adapters import AdapterRunHandle
        adapter = LocalShellAdapter()
        fake = AdapterRunHandle(handle_id="nope", backend_id="local-shell", spawned_at=0, spec_id="x")
        result = adapter.collect(fake)
        assert result.status == AdapterStatus.FAILED
        assert "unknown handle" in result.error
