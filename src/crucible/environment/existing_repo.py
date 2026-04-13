from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class ExistingRepoEnvironment:
    repo_path: str
    ecosystem: str
    language: str
    runtime: str
    package_manager: str
    build_tool: str
    test_tool: str
    confidence: str
    evidence: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class ExistingRepoStrategy:
    ecosystem: str
    toolchain: str
    provisioner: str
    install_command: list[str]
    fallback_commands: list[list[str]] = field(default_factory=list)
    environment_path: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class ExistingRepoProvisionResult:
    detected: ExistingRepoEnvironment
    strategy: ExistingRepoStrategy
    status: str
    metadata_path: str
    commands_run: list[list[str]] = field(default_factory=list)
    stdout: list[str] = field(default_factory=list)
    stderr: list[str] = field(default_factory=list)
    created_paths: list[str] = field(default_factory=list)
    readiness_checks: list[list[str]] = field(default_factory=list)
    readiness_failures: list[str] = field(default_factory=list)
    failure_class: str | None = None
    failure_reason: str = ""
    missing_executables: list[str] = field(default_factory=list)
    provisioned_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExistingRepoProvisionError(RuntimeError):
    def __init__(self, message: str, *, failure_class: str, result: ExistingRepoProvisionResult) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.result = result


def detect_existing_repo_environment(repo_path: str) -> ExistingRepoEnvironment:
    root = Path(repo_path)
    if not root.is_dir():
        raise FileNotFoundError(f"repo path does not exist: {repo_path}")

    evidence: dict[str, list[str]] = {}
    notes: list[str] = []

    def hit(bucket: str, item: str) -> None:
        evidence.setdefault(bucket, []).append(item)

    if (root / "pyproject.toml").is_file() or (root / "requirements.txt").is_file() or (root / "setup.py").is_file():
        ecosystem = language = runtime = "python"
        hit("language", "python markers")
        if (root / "uv.lock").is_file():
            package_manager = "uv"
            hit("package_manager", "uv.lock")
        elif (root / "poetry.lock").is_file():
            package_manager = "poetry"
            hit("package_manager", "poetry.lock")
        elif (root / "Pipfile.lock").is_file() or (root / "Pipfile").is_file():
            package_manager = "pipenv"
            hit("package_manager", "Pipfile/Pipfile.lock")
        elif (root / "requirements.txt").is_file():
            package_manager = "pip"
            hit("package_manager", "requirements.txt")
        else:
            package_manager = "unknown"
            notes.append("no explicit Python package manager detected")

        build_tool = "setuptools"
        test_tool = "unknown"
        if (root / "pytest.ini").is_file() or (root / "conftest.py").is_file():
            test_tool = "pytest"
        if (root / "pyproject.toml").is_file():
            text = (root / "pyproject.toml").read_text(errors="ignore")
            try:
                import tomllib
                parsed = tomllib.loads(text)
            except Exception:
                parsed = {}
            build_system = parsed.get("build-system", {}) if isinstance(parsed, dict) else {}
            build_requires = json.dumps(build_system.get("requires", [])) if isinstance(build_system, dict) else ""
            tool_section = parsed.get("tool", {}) if isinstance(parsed, dict) else {}
            optional = parsed.get("project", {}).get("optional-dependencies", {}) if isinstance(parsed.get("project", {}), dict) else {}
            optional_blob = json.dumps(optional)
            if "hatchling" in build_requires:
                build_tool = "hatchling"
                hit("build_tool", "pyproject.toml:build-system.requires:hatchling")
            elif "poetry.core" in build_requires or "poetry" in json.dumps(tool_section.get("poetry", {})):
                build_tool = "poetry"
                hit("build_tool", "pyproject.toml:poetry")
            elif "setuptools" in build_requires:
                hit("build_tool", "pyproject.toml:build-system.requires:setuptools")
            if "[tool.pytest" in text or "pytest" in json.dumps(tool_section.get("pytest", {})) or "pytest" in optional_blob:
                test_tool = "pytest"
                hit("test_tool", "pyproject.toml tool/dependencies:pytest")
    elif (root / "package.json").is_file():
        ecosystem = runtime = language = "node"
        if (root / "tsconfig.json").is_file():
            language = "typescript"
            hit("language", "tsconfig.json")
        else:
            hit("language", "package.json")
        pkg = json.loads((root / "package.json").read_text() or "{}")
        package_manager_field = str(pkg.get("packageManager", ""))
        if (root / "pnpm-lock.yaml").is_file() or package_manager_field.startswith("pnpm@"):
            package_manager = "pnpm"
            hit("package_manager", "pnpm-lock.yaml/packageManager")
        elif (root / "yarn.lock").is_file() or package_manager_field.startswith("yarn@"):
            package_manager = "yarn"
            hit("package_manager", "yarn.lock/packageManager")
        else:
            package_manager = "npm"
            hit("package_manager", "default npm")
        scripts = pkg.get("scripts", {}) if isinstance(pkg.get("scripts"), dict) else {}
        deps_blob = json.dumps({"dependencies": pkg.get("dependencies", {}), "devDependencies": pkg.get("devDependencies", {})})
        if "next" in deps_blob:
            build_tool = "next"
        elif "vite" in deps_blob:
            build_tool = "vite"
        elif "webpack" in deps_blob:
            build_tool = "webpack"
        elif "build" in scripts:
            build_tool = "npm-scripts"
        else:
            build_tool = "node"
        if "vitest" in deps_blob:
            test_tool = "vitest"
        elif "jest" in deps_blob:
            test_tool = "jest"
        elif "test" in scripts:
            test_tool = "npm-test"
        else:
            test_tool = "node:test"
    elif (root / "Cargo.toml").is_file():
        ecosystem = language = runtime = "rust"
        package_manager = build_tool = test_tool = "cargo"
        hit("language", "Cargo.toml")
    elif (root / "go.mod").is_file():
        ecosystem = language = runtime = "go"
        package_manager = build_tool = test_tool = "go"
        hit("language", "go.mod")
    elif (root / "Gemfile").is_file():
        ecosystem = language = runtime = "ruby"
        package_manager = build_tool = test_tool = "bundler"
        hit("language", "Gemfile")
    else:
        return ExistingRepoEnvironment(
            repo_path=str(root),
            ecosystem="unknown",
            language="unknown",
            runtime="unknown",
            package_manager="unknown",
            build_tool="unknown",
            test_tool="unknown",
            confidence="low",
            evidence=evidence,
            notes=["unable to infer repository ecosystem from standard markers"],
        )

    confidence = "high" if evidence else "medium"
    return ExistingRepoEnvironment(
        repo_path=str(root),
        ecosystem=ecosystem,
        language=language,
        runtime=runtime,
        package_manager=package_manager,
        build_tool=build_tool,
        test_tool=test_tool,
        confidence=confidence,
        evidence=evidence,
        notes=notes,
    )


def choose_environment_strategy(detected: ExistingRepoEnvironment) -> ExistingRepoStrategy:
    root = Path(detected.repo_path)
    if detected.ecosystem == "python":
        if detected.package_manager in {"uv", "unknown"}:
            if (root / "pyproject.toml").is_file():
                return ExistingRepoStrategy(
                    ecosystem="python",
                    toolchain="uv",
                    provisioner="uv-sync",
                    install_command=["uv", "sync"],
                    fallback_commands=[["uv", "pip", "install", "-r", "requirements.txt"]] if (root / "requirements.txt").is_file() else [],
                    environment_path=str(root / ".venv"),
                    notes=["defaulted Python existing-repo setup to uv"] if detected.package_manager == "unknown" else [],
                )
        if (root / "requirements.txt").is_file():
            return ExistingRepoStrategy(
                ecosystem="python",
                toolchain="uv",
                provisioner="uv-pip",
                install_command=["uv", "pip", "install", "-r", "requirements.txt"],
                fallback_commands=[],
                environment_path=str(root / ".venv"),
                notes=["defaulted Python existing-repo setup to uv"],
            )
        return ExistingRepoStrategy(
            ecosystem="python",
            toolchain="uv",
            provisioner="uv-sync",
            install_command=["uv", "sync"],
            fallback_commands=[],
            environment_path=str(root / ".venv"),
            notes=["defaulted Python existing-repo setup to uv"],
        )

    if detected.ecosystem == "node":
        return ExistingRepoStrategy(
            ecosystem="node",
            toolchain=detected.package_manager if detected.package_manager in {"npm", "pnpm", "yarn"} else "npm",
            provisioner="node-install",
            install_command=["npm", "install"] if detected.package_manager == "npm" else [detected.package_manager, "install"],
            fallback_commands=[["npm", "install"]] if detected.package_manager != "npm" else [],
            environment_path=str(root / "node_modules"),
            notes=["defaulted Node existing-repo setup to npm"] if detected.package_manager == "npm" else [],
        )

    if detected.ecosystem == "rust":
        return ExistingRepoStrategy(detected.ecosystem, "cargo", "cargo-fetch", ["cargo", "fetch"], environment_path=str(root / "target"))
    if detected.ecosystem == "go":
        return ExistingRepoStrategy(detected.ecosystem, "go", "go-mod-download", ["go", "mod", "download"], environment_path=str(root / "go.sum"))
    if detected.ecosystem == "ruby":
        return ExistingRepoStrategy(detected.ecosystem, "bundler", "bundle-install", ["bundle", "install"], environment_path=str(root / "vendor" / "bundle"))

    return ExistingRepoStrategy(
        ecosystem=detected.ecosystem,
        toolchain="unknown",
        provisioner="none",
        install_command=[],
        notes=["no provisioning strategy available for this ecosystem"],
    )


def ensure_existing_repo_environment(repo_path: str) -> ExistingRepoProvisionResult:
    root = Path(repo_path)
    metadata_dir = root / ".crucible"
    metadata_dir.mkdir(exist_ok=True)
    metadata_path = metadata_dir / "environment.json"

    detected = detect_existing_repo_environment(str(root))
    strategy = choose_environment_strategy(detected)
    result = ExistingRepoProvisionResult(
        detected=detected,
        strategy=strategy,
        status="skipped",
        metadata_path=str(metadata_path),
    )

    if detected.ecosystem == "unknown" or not strategy.install_command:
        result.failure_class = "ambiguity_block"
        result.failure_reason = "no_supported_strategy"
        _write_metadata(metadata_path, result)
        return result

    if _environment_already_usable(root, detected, strategy, result=result):
        result.status = "ready"
        if strategy.environment_path and Path(strategy.environment_path).exists():
            result.created_paths = [strategy.environment_path]
        _write_metadata(metadata_path, result)
        return result

    commands = _provisioning_commands(root, detected, strategy)
    for index, command in enumerate(commands):
        if not command:
            continue
        result.commands_run.append(command)
        try:
            proc = subprocess.run(command, cwd=root, capture_output=True, text=True)
        except FileNotFoundError as exc:
            missing = command[0] if command else "unknown"
            result.status = "failed"
            result.failure_class = "environment_block"
            result.failure_reason = f"missing required executable: {missing}"
            result.missing_executables.append(missing)
            result.stderr.append(str(exc))
            _write_metadata(metadata_path, result)
            raise ExistingRepoProvisionError(result.failure_reason, failure_class=result.failure_class, result=result) from exc
        result.stdout.append(proc.stdout)
        result.stderr.append(proc.stderr)
        if proc.returncode != 0:
            if index < len(commands) - 1:
                continue
            result.status = "failed"
            result.failure_reason = proc.stderr.strip() or proc.stdout.strip() or f"command failed: {' '.join(command)}"
            result.failure_class = _infer_failure_class(result.failure_reason)
            _write_metadata(metadata_path, result)
            raise ExistingRepoProvisionError(result.failure_reason, failure_class=result.failure_class, result=result)

    install_confirmed = any(command == strategy.install_command for command in result.commands_run)
    if not _environment_already_usable(root, detected, strategy, install_confirmed=install_confirmed, result=result):
        result.status = "failed"
        result.failure_class = "environment_block"
        if not result.failure_reason:
            result.failure_reason = "provisioning completed without producing a usable environment"
        _write_metadata(metadata_path, result)
        raise ExistingRepoProvisionError(result.failure_reason, failure_class=result.failure_class, result=result)

    result.status = "provisioned"
    if detected.ecosystem == "node" and strategy.environment_path and not Path(strategy.environment_path).exists():
        Path(strategy.environment_path).mkdir(parents=True, exist_ok=True)
    if strategy.environment_path and Path(strategy.environment_path).exists():
        result.created_paths.append(strategy.environment_path)
    _write_metadata(metadata_path, result)
    return result


def _provisioning_commands(root: Path, detected: ExistingRepoEnvironment, strategy: ExistingRepoStrategy) -> list[list[str]]:
    bootstrap = _bootstrap_command(root, detected, strategy)
    commands = [bootstrap] if bootstrap else []
    commands.append(strategy.install_command)
    commands.extend(strategy.fallback_commands)
    return [command for command in commands if command]


def _bootstrap_command(root: Path, detected: ExistingRepoEnvironment, strategy: ExistingRepoStrategy) -> list[str] | None:
    if detected.ecosystem == "python" and strategy.toolchain == "uv" and not (root / ".venv").exists():
        return ["uv", "venv"]
    return None


def _environment_already_usable(
    root: Path,
    detected: ExistingRepoEnvironment,
    strategy: ExistingRepoStrategy,
    *,
    install_confirmed: bool = False,
    result: ExistingRepoProvisionResult | None = None,
) -> bool:
    if detected.ecosystem == "python":
        venv = root / ".venv"
        if not venv.is_dir():
            return False
        if not (venv / "pyvenv.cfg").is_file():
            return False
        python_bin = _python_executable_in_venv(venv)
        if python_bin is None or not python_bin.is_file():
            return False
        if _python_requires_install_marker(root):
            install_ready = install_confirmed or _provision_sentinel_exists(root, strategy)
            if not install_ready:
                return False
        if not _python_validation_tool_ready(root, detected, python_bin, result=result):
            return False
        return True
    if detected.ecosystem == "node":
        node_modules = root / "node_modules"
        if not node_modules.is_dir():
            return False
        if not any(node_modules.iterdir()):
            return False
        return True
    if detected.ecosystem == "rust":
        return (root / "target").exists()
    return False


def _python_executable_in_venv(venv: Path) -> Path | None:
    for candidate in (venv / "bin" / "python", venv / "Scripts" / "python.exe"):
        if candidate.exists():
            return candidate
    return None


def _python_validation_tool_ready(
    root: Path,
    detected: ExistingRepoEnvironment,
    python_bin: Path,
    *,
    result: ExistingRepoProvisionResult | None = None,
) -> bool:
    if detected.test_tool != "pytest":
        return True
    command = [str(python_bin), "-m", "pytest", "--version"]
    if result is not None:
        result.readiness_checks.append(command)
    try:
        proc = subprocess.run(command, cwd=root, capture_output=True, text=True)
    except OSError as exc:
        if result is not None:
            result.readiness_failures.append(str(exc))
            result.failure_reason = f"pytest readiness check could not run: {exc}"
        return False
    if proc.returncode == 0:
        return True
    failure = proc.stderr.strip() or proc.stdout.strip() or "pytest readiness check failed"
    if result is not None:
        result.readiness_failures.append(failure)
        result.failure_reason = f"python environment missing runnable pytest: {failure}"
    return False


def _python_requires_install_marker(root: Path) -> bool:
    if (root / "pyproject.toml").is_file():
        return True
    req = root / "requirements.txt"
    return req.is_file() and bool(req.read_text(errors="ignore").strip())


def _provision_sentinel_exists(root: Path, strategy: ExistingRepoStrategy) -> bool:
    metadata_path = root / ".crucible" / "environment.json"
    if not metadata_path.is_file():
        return False
    try:
        payload = json.loads(metadata_path.read_text())
    except json.JSONDecodeError:
        return False
    if payload.get("status") not in {"provisioned", "ready"}:
        return False
    strategy_payload = payload.get("strategy") if isinstance(payload.get("strategy"), dict) else {}
    if strategy_payload.get("toolchain") != strategy.toolchain:
        return False
    recorded_commands = payload.get("commands_run") if isinstance(payload.get("commands_run"), list) else []
    return any(command == strategy.install_command for command in recorded_commands)


def _infer_failure_class(message: str) -> str:
    text = message.lower()
    dependency_markers = [
        "no module named",
        "cannot find module",
        "module not found",
        "missing script",
        "could not resolve",
        "requires a package manager lockfile",
    ]
    environment_markers = [
        "command not found",
        "not found",
        "uv: ",
        "npm: ",
        "node: ",
        "python: ",
        "executable file not found",
        "missing required executable",
    ]
    if any(marker in text for marker in dependency_markers):
        return "missing_dependency"
    if any(marker in text for marker in environment_markers):
        return "environment_block"
    return "environment_block"


def _write_metadata(path: Path, result: ExistingRepoProvisionResult) -> None:
    path.write_text(json.dumps(result.to_dict(), indent=2))
