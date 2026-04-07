"""Evidence store for Crucible v5.4."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket


@dataclass
class EvidenceManifest:
    attempt_id: str
    artifacts: list[str] = field(default_factory=list)
    diffs: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    criterion_results: dict[str, bool] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    review_verdict: str | None = None
    unresolved_risks: list[str] = field(default_factory=list)

    def add_artifact(self, path: str):
        if path not in self.artifacts:
            self.artifacts.append(path)
            self.evidence_refs.append(path)

    def add_log(self, path: str):
        if path not in self.logs:
            self.logs.append(path)
            self.evidence_refs.append(path)

    def set_criterion_result(self, criterion: str, passed: bool):
        self.criterion_results[criterion] = passed

    def all_criteria_passed(self) -> bool:
        return all(self.criterion_results.values()) if self.criterion_results else False

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "artifacts": self.artifacts,
            "diffs": self.diffs,
            "logs": self.logs,
            "criterion_results": self.criterion_results,
            "evidence_refs": self.evidence_refs,
            "review_verdict": self.review_verdict,
            "unresolved_risks": self.unresolved_risks,
        }


class EvidenceStore:
    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or Path.home() / ".crucible" / "evidence"
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _run_dir(self, run_id: str) -> Path:
        run_dir = self.base_path / run_id
        run_dir.mkdir(exist_ok=True)
        return run_dir

    def store_evidence_packet(self, packet: FailureEvidencePacket) -> Path:
        run_id = packet.task_id or packet.attempt_id.split('-attempt-')[0]
        file_path = self._run_dir(run_id) / f"{packet.attempt_id}_evidence.json"
        file_path.write_text(json.dumps(packet.to_dict(), indent=2))
        return file_path

    def store_manifest(self, manifest: EvidenceManifest) -> Path:
        run_id = manifest.attempt_id.split('-attempt-')[0]
        file_path = self._run_dir(run_id) / f"{manifest.attempt_id}_manifest.json"
        file_path.write_text(json.dumps(manifest.to_dict(), indent=2))
        return file_path

    def load_evidence_packet(self, attempt_id: str) -> FailureEvidencePacket | None:
        run_id = attempt_id.split('-attempt-')[0]
        file_path = self.base_path / run_id / f"{attempt_id}_evidence.json"
        if not file_path.exists():
            return None
        data = json.loads(file_path.read_text())
        return FailureEvidencePacket(
            failure_class=FailureClass(data["failure_class"]),
            attempt_id=data["attempt_id"],
            criterion=data.get("criterion"),
            evidence_refs=data.get("evidence_refs", []),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            reproducible=data.get("reproducible", True),
            error_message=data.get("error_message"),
            root_cause_hypothesis=data.get("root_cause_hypothesis"),
            prior_attempts=data.get("prior_attempts", []),
            task_id=data.get("task_id"),
            signature=data.get("signature"),
            human_summary=data.get("human_summary", ""),
            machine_action=data.get("machine_action", ""),
            consumes_budget=data.get("consumes_budget", True),
            recommended_next_roles=data.get("recommended_next_roles", []),
            failing_command=data.get("failing_command"),
            missing_artifacts=data.get("missing_artifacts", []),
            recent_lane=data.get("recent_lane"),
            metadata=data.get("metadata", {}),
        )

    def load_manifest(self, attempt_id: str) -> EvidenceManifest | None:
        run_id = attempt_id.split('-attempt-')[0]
        file_path = self.base_path / run_id / f"{attempt_id}_manifest.json"
        if not file_path.exists():
            return None
        data = json.loads(file_path.read_text())
        return EvidenceManifest(
            attempt_id=data["attempt_id"],
            artifacts=data.get("artifacts", []),
            diffs=data.get("diffs", []),
            logs=data.get("logs", []),
            criterion_results=data.get("criterion_results", {}),
            evidence_refs=data.get("evidence_refs", []),
            review_verdict=data.get("review_verdict"),
            unresolved_risks=data.get("unresolved_risks", []),
        )

    def get_run_evidence(self, run_id: str) -> list[dict]:
        run_dir = self.base_path / run_id
        if not run_dir.exists():
            return []
        return [json.loads(f.read_text()) for f in sorted(run_dir.glob("*_evidence.json"))]
