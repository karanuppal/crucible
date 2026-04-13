import json
import os
from pathlib import Path

import pytest

from crucible.environment.existing_repo import (
    ExistingRepoProvisionError,
    choose_environment_strategy,
    detect_existing_repo_environment,
    ensure_existing_repo_environment,
)


def _write_fake_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def test_detects_python_uv_repo(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"
version = "0.1.0"
[tool.pytest.ini_options]
testpaths = ["tests"]
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
""".strip()
    )
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "tests").mkdir()

    detected = detect_existing_repo_environment(str(tmp_path))
    strategy = choose_environment_strategy(detected)

    assert detected.ecosystem == "python"
    assert detected.package_manager == "uv"
    assert detected.test_tool == "pytest"
    assert strategy.toolchain == "uv"
    assert strategy.install_command == ["uv", "sync"]


def test_detects_node_and_defaults_to_npm(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "demo",
        "version": "1.0.0",
        "scripts": {"test": "node --test", "build": "node build.js"},
    }))
    (tmp_path / "tsconfig.json").write_text("{}")

    detected = detect_existing_repo_environment(str(tmp_path))
    strategy = choose_environment_strategy(detected)

    assert detected.ecosystem == "node"
    assert detected.language == "typescript"
    assert detected.package_manager == "npm"
    assert detected.test_tool == "npm-test"
    assert strategy.install_command == ["npm", "install"]


def test_python_default_strategy_uses_uv_for_requirements_repo(tmp_path):
    (tmp_path / "requirements.txt").write_text("")
    (tmp_path / "setup.py").write_text("from setuptools import setup; setup(name='demo')")

    detected = detect_existing_repo_environment(str(tmp_path))
    strategy = choose_environment_strategy(detected)

    assert detected.ecosystem == "python"
    assert strategy.toolchain == "uv"
    assert strategy.install_command == ["uv", "pip", "install", "-r", "requirements.txt"]


@pytest.mark.integration
def test_provisions_python_repo_runs_bootstrap_and_install(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv.log"
    _write_fake_executable(
        bin_dir / "uv",
        f'''#!/bin/sh
set -eu
echo "$*" >> "{log_path}"
if [ "$1" = "venv" ]; then
  mkdir -p .venv/bin
  cat > .venv/bin/python <<'EOF'
#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "pytest" ] && [ "$3" = "--version" ]; then
  exit 0
fi
exit 0
EOF
  chmod +x .venv/bin/python
  touch .venv/pyvenv.cfg
  exit 0
fi
if [ "$1" = "sync" ]; then
  touch .venv/installed.ok
  exit 0
fi
exit 99
''',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"
version = "0.1.0"
dependencies = []
[tool.pytest.ini_options]
testpaths = ["tests"]
""".strip()
    )

    result = ensure_existing_repo_environment(str(tmp_path))

    assert result.status == "provisioned"
    assert result.commands_run == [["uv", "venv"], ["uv", "sync"]]
    assert result.readiness_checks == [[str(tmp_path / ".venv" / "bin" / "python"), "-m", "pytest", "--version"]]
    assert (tmp_path / ".venv" / "installed.ok").is_file()
    payload = json.loads((tmp_path / ".crucible" / "environment.json").read_text())
    assert payload["strategy"]["toolchain"] == "uv"
    assert payload["commands_run"] == [["uv", "venv"], ["uv", "sync"]]
    assert payload["readiness_checks"] == [[str(tmp_path / ".venv" / "bin" / "python"), "-m", "pytest", "--version"]]
    assert log_path.read_text().splitlines() == ["venv", "sync"]


@pytest.mark.integration
def test_provisions_node_repo_with_npm_default(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_executable(
        bin_dir / "npm",
        "#!/bin/sh\nset -eu\nmkdir -p node_modules/pkg\nexit 0\n",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "demo",
        "version": "1.0.0",
        "scripts": {"test": "node --test"},
    }))

    result = ensure_existing_repo_environment(str(tmp_path))

    assert result.status == "provisioned"
    assert (tmp_path / "node_modules" / "pkg").is_dir()
    payload = json.loads((tmp_path / ".crucible" / "environment.json").read_text())
    assert payload["strategy"]["toolchain"] == "npm"


def test_missing_toolchain_becomes_structured_environment_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "missing-bin"))
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"
version = "0.1.0"
""".strip()
    )

    with pytest.raises(ExistingRepoProvisionError) as excinfo:
        ensure_existing_repo_environment(str(tmp_path))

    result = excinfo.value.result
    assert excinfo.value.failure_class == "environment_block"
    assert result.status == "failed"
    assert result.failure_class == "environment_block"
    assert result.failure_reason == "missing required executable: uv"
    assert result.missing_executables == ["uv"]
    payload = json.loads((tmp_path / ".crucible" / "environment.json").read_text())
    assert payload["failure_class"] == "environment_block"
    assert payload["missing_executables"] == ["uv"]


def test_python_ready_check_rejects_bare_venv_without_install_sentinel(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"
version = "0.1.0"
""".strip()
    )
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /tmp/python\n")
    (venv_bin / "python").write_text("#!/bin/sh\nexit 0\n")
    (venv_bin / "python").chmod(0o755)

    detected = detect_existing_repo_environment(str(tmp_path))
    strategy = choose_environment_strategy(detected)

    from crucible.environment.existing_repo import _environment_already_usable

    assert _environment_already_usable(tmp_path, detected, strategy) is False


def test_python_ready_check_rejects_installed_sentinel_without_runnable_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"
version = "0.1.0"
[tool.pytest.ini_options]
testpaths = ["tests"]
""".strip()
    )
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /tmp/python\n")
    (venv_bin / "python").write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-m\" ] && [ \"$2\" = \"pytest\" ] && [ \"$3\" = \"--version\" ]; then\n"
        "  echo 'No module named pytest' 1>&2\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )
    (venv_bin / "python").chmod(0o755)
    metadata_dir = tmp_path / ".crucible"
    metadata_dir.mkdir()
    (metadata_dir / "environment.json").write_text(json.dumps({
        "status": "provisioned",
        "strategy": {"toolchain": "uv"},
        "commands_run": [["uv", "sync"]],
    }))

    detected = detect_existing_repo_environment(str(tmp_path))
    strategy = choose_environment_strategy(detected)

    from crucible.environment.existing_repo import ExistingRepoProvisionResult, _environment_already_usable

    result = ExistingRepoProvisionResult(
        detected=detected,
        strategy=strategy,
        status="ready",
        metadata_path=str(metadata_dir / "environment.json"),
    )

    assert _environment_already_usable(tmp_path, detected, strategy, result=result) is False
    assert result.readiness_checks == [[str(venv_bin / "python"), "-m", "pytest", "--version"]]
    assert result.readiness_failures == ["No module named pytest"]
    assert "missing runnable pytest" in result.failure_reason


@pytest.mark.integration
def test_provisioning_rejects_python_env_without_runnable_pytest(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_executable(
        bin_dir / "uv",
        '''#!/bin/sh
set -eu
if [ "$1" = "venv" ]; then
  mkdir -p .venv/bin
  cat > .venv/bin/python <<'EOF'
#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "pytest" ] && [ "$3" = "--version" ]; then
  echo 'No module named pytest' 1>&2
  exit 1
fi
exit 0
EOF
  chmod +x .venv/bin/python
  touch .venv/pyvenv.cfg
  exit 0
fi
if [ "$1" = "sync" ]; then
  touch .venv/installed.ok
  exit 0
fi
exit 99
''',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"
version = "0.1.0"
[tool.pytest.ini_options]
testpaths = ["tests"]
""".strip()
    )

    with pytest.raises(ExistingRepoProvisionError, match="missing runnable pytest") as excinfo:
        ensure_existing_repo_environment(str(tmp_path))

    result = excinfo.value.result
    assert result.failure_class == "environment_block"
    assert result.readiness_checks == [[str(tmp_path / ".venv" / "bin" / "python"), "-m", "pytest", "--version"]]
    assert result.readiness_failures == ["No module named pytest"]
    payload = json.loads((tmp_path / ".crucible" / "environment.json").read_text())
    assert payload["status"] == "failed"
    assert payload["failure_class"] == "environment_block"
    assert payload["readiness_failures"] == ["No module named pytest"]


def test_node_ready_check_rejects_empty_node_modules(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "demo", "version": "1.0.0"}))
    (tmp_path / "node_modules").mkdir()

    detected = detect_existing_repo_environment(str(tmp_path))
    strategy = choose_environment_strategy(detected)

    from crucible.environment.existing_repo import _environment_already_usable

    assert _environment_already_usable(tmp_path, detected, strategy) is False
