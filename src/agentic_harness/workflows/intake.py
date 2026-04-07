"""Phase 5: Existing-project intake.

Inspects an existing repo and produces an IntakeReport with:
- Detected language(s)
- Detected build/test framework(s)
- Confidence per detection
- Uncertainty flags (NEVER hallucinate — surface ambiguity)
- Detected dependencies
- Existing CI present?

Hard rule: ambiguous repos must surface uncertainty, not invent classification.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCERTAIN = "uncertain"  # do not proceed without human input


@dataclass
class Detection:
    """A single detection result with confidence."""
    label: str
    evidence: list[str]  # files/patterns that support the detection
    confidence: Confidence


@dataclass
class IntakeReport:
    """Complete report from inspecting a repo."""
    repo_path: str
    languages: list[Detection] = field(default_factory=list)
    build_systems: list[Detection] = field(default_factory=list)
    test_frameworks: list[Detection] = field(default_factory=list)
    package_managers: list[Detection] = field(default_factory=list)
    has_ci: bool = False
    ci_systems: list[str] = field(default_factory=list)
    has_git: bool = False
    has_readme: bool = False
    uncertainty_flags: list[str] = field(default_factory=list)
    archetype: str = ""  # "clean" | "messy" | "broken" | "ambiguous"
    
    def has_blocking_uncertainty(self) -> bool:
        return len(self.uncertainty_flags) > 0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_path": self.repo_path,
            "languages": [_detection_dict(d) for d in self.languages],
            "build_systems": [_detection_dict(d) for d in self.build_systems],
            "test_frameworks": [_detection_dict(d) for d in self.test_frameworks],
            "package_managers": [_detection_dict(d) for d in self.package_managers],
            "has_ci": self.has_ci,
            "ci_systems": list(self.ci_systems),
            "has_git": self.has_git,
            "has_readme": self.has_readme,
            "uncertainty_flags": list(self.uncertainty_flags),
            "archetype": self.archetype,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntakeReport":
        return cls(
            repo_path=data["repo_path"],
            languages=[_detection_from_dict(d) for d in data.get("languages", [])],
            build_systems=[_detection_from_dict(d) for d in data.get("build_systems", [])],
            test_frameworks=[_detection_from_dict(d) for d in data.get("test_frameworks", [])],
            package_managers=[_detection_from_dict(d) for d in data.get("package_managers", [])],
            has_ci=data.get("has_ci", False),
            ci_systems=list(data.get("ci_systems", [])),
            has_git=data.get("has_git", False),
            has_readme=data.get("has_readme", False),
            uncertainty_flags=list(data.get("uncertainty_flags", [])),
            archetype=data.get("archetype", ""),
        )
    
    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        os.replace(tmp, path)
    
    @classmethod
    def load(cls, path: str) -> "IntakeReport":
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))


def _detection_dict(d: Detection) -> dict[str, Any]:
    return {
        "label": d.label,
        "evidence": list(d.evidence),
        "confidence": d.confidence.value,
    }


def _detection_from_dict(d: dict[str, Any]) -> Detection:
    return Detection(
        label=d["label"],
        evidence=list(d["evidence"]),
        confidence=Confidence(d["confidence"]),
    )


# File-based signatures
LANGUAGE_SIGNATURES: dict[str, list[str]] = {
    "python": ["pyproject.toml", "setup.py", "requirements.txt", "Pipfile"],
    "javascript": ["package.json"],
    "typescript": ["tsconfig.json"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "ruby": ["Gemfile"],
}

PACKAGE_MANAGER_SIGNATURES: dict[str, list[str]] = {
    "uv": ["uv.lock"],
    "poetry": ["poetry.lock"],
    "pip": ["requirements.txt"],
    "pipenv": ["Pipfile.lock"],
    "npm": ["package-lock.json"],
    "yarn": ["yarn.lock"],
    "pnpm": ["pnpm-lock.yaml"],
    "cargo": ["Cargo.lock"],
}

TEST_FRAMEWORK_SIGNATURES: dict[str, dict[str, Any]] = {
    "pytest": {"files": ["pytest.ini", "conftest.py"], "in_pyproject": "pytest"},
    "jest": {"files": ["jest.config.js", "jest.config.ts"], "in_package": "jest"},
    "vitest": {"files": ["vitest.config.ts", "vitest.config.js"]},
    "mocha": {"in_package": "mocha"},
    # NOTE: 'unittest' inference from bare 'tests/' directory removed —
    # was a hallucination source. Tests dir alone surfaces as uncertainty,
    # not an inferred framework.
}

CI_SIGNATURES: dict[str, str] = {
    "github_actions": ".github/workflows",
    "gitlab_ci": ".gitlab-ci.yml",
    "circleci": ".circleci/config.yml",
    "travis": ".travis.yml",
}


def inspect_repo(repo_path: str) -> IntakeReport:
    """Inspect a repo and produce a structured intake report.
    
    Hard rule: surface uncertainty rather than guess.
    """
    if not os.path.isdir(repo_path):
        raise FileNotFoundError(f"Repo path does not exist: {repo_path}")
    
    report = IntakeReport(repo_path=repo_path)
    
    # Git presence
    report.has_git = os.path.isdir(os.path.join(repo_path, ".git"))
    if not report.has_git:
        report.uncertainty_flags.append("no_git_directory")
    
    # README
    for readme in ["README.md", "README.rst", "README.txt", "README"]:
        if os.path.isfile(os.path.join(repo_path, readme)):
            report.has_readme = True
            break
    
    # Detect languages
    for lang, files in LANGUAGE_SIGNATURES.items():
        evidence = [f for f in files if os.path.isfile(os.path.join(repo_path, f))]
        if evidence:
            report.languages.append(Detection(
                label=lang,
                evidence=evidence,
                confidence=Confidence.HIGH if len(evidence) > 1 else Confidence.MEDIUM,
            ))
    
    # Detect package managers
    for pm, files in PACKAGE_MANAGER_SIGNATURES.items():
        evidence = [f for f in files if os.path.isfile(os.path.join(repo_path, f))]
        if evidence:
            report.package_managers.append(Detection(
                label=pm,
                evidence=evidence,
                confidence=Confidence.HIGH,
            ))
    
    # Detect test frameworks (deeper)
    pyproject_path = os.path.join(repo_path, "pyproject.toml")
    pyproject_text = ""
    if os.path.isfile(pyproject_path):
        try:
            with open(pyproject_path) as f:
                pyproject_text = f.read()
        except Exception:
            pass
    
    for tf, sig in TEST_FRAMEWORK_SIGNATURES.items():
        evidence = []
        confidence = Confidence.MEDIUM
        
        if "files" in sig:
            for fn in sig["files"]:
                if os.path.isfile(os.path.join(repo_path, fn)):
                    evidence.append(fn)
        
        if "in_pyproject" in sig and sig["in_pyproject"] in pyproject_text:
            evidence.append(f"pyproject.toml mentions {sig['in_pyproject']}")
            confidence = Confidence.HIGH
        
        if evidence:
            report.test_frameworks.append(Detection(
                label=tf, evidence=evidence, confidence=confidence,
            ))
    
    # CI detection
    for ci_name, ci_path in CI_SIGNATURES.items():
        full = os.path.join(repo_path, ci_path)
        if os.path.exists(full):
            report.has_ci = True
            report.ci_systems.append(ci_name)
    
    # Determine archetype
    report.archetype = _determine_archetype(report)
    
    # Surface uncertainty
    if not report.languages:
        report.uncertainty_flags.append("no_language_detected")
    if len(report.languages) > 2:
        report.uncertainty_flags.append("multiple_languages_detected")
    if report.languages and not report.test_frameworks:
        report.uncertainty_flags.append("no_test_framework_detected")
    if not report.package_managers and report.languages:
        report.uncertainty_flags.append("no_package_manager_detected")
    
    return report


def _determine_archetype(report: IntakeReport) -> str:
    """Classify the repo into an archetype.
    
    Archetypes:
    - clean: lang + pm + tests + ci + readme + git
    - messy: lang detected, missing some signals
    - broken: lang detected but conflicting/missing critical signals
              (no PM AND no git AND no readme AND no tests)
    - ambiguous: no language at all OR mixed signals
    """
    has_lang = bool(report.languages)
    has_pm = bool(report.package_managers)
    has_tests = bool(report.test_frameworks)
    has_ci = report.has_ci
    
    if not has_lang:
        return "ambiguous"
    
    # Multiple unrelated languages with no clear primary = ambiguous
    if len(report.languages) >= 3:
        return "ambiguous"
    
    # Clean: all the signals
    if has_pm and has_tests and has_ci and report.has_readme and report.has_git:
        return "clean"
    
    # Broken: language detected but no infra at all (no pm, no tests, no git)
    # This is a "started but never finished" repo
    missing_critical = sum([
        not has_pm,
        not has_tests,
        not report.has_git,
        not report.has_readme,
    ])
    if missing_critical >= 3:
        return "broken"
    
    # Otherwise messy
    return "messy"
