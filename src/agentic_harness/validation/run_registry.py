"""Phase 3: Trusted run registry.

Provenance cannot be self-attested. The RunRegistry is the authoritative
source for: which command ran, which run produced which artifacts.

The validator looks up the run registry instead of trusting caller metadata.
This closes the "forged executed_command" attack.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from agentic_harness.validation.artifact import ArtifactRef


@dataclass
class RunRecord:
    """Authoritative record of a verification command execution."""
    run_id: str
    command: str
    exit_code: int
    stdout_path: str  # path to captured stdout
    stderr_path: str  # path to captured stderr
    started_at: float
    finished_at: float
    artifact_ids: list[str] = field(default_factory=list)
    # Map artifact_id -> full fingerprint (authoritative binding)
    # Fingerprint includes: content_hash, path, type, immutable
    artifact_fingerprints: dict[str, dict[str, Any]] = field(default_factory=dict)


class RunRegistry:
    """Trusted registry for verification runs.
    
    Only a run actually recorded here is considered to have 'executed'.
    Callers cannot fake executed_command or producer_run_id — the registry
    must confirm via record_run().
    """
    
    def __init__(self, path: str | None = None) -> None:
        self._records: dict[str, RunRecord] = {}
        self._path = path
        if path and os.path.exists(path):
            self._load()
    
    def record_run(
        self,
        command: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        started_at: float,
        finished_at: float,
        artifacts: list[ArtifactRef] | None = None,
    ) -> RunRecord:
        """Record a verification run. Only recorded runs can be used as provenance."""
        run_id = f"vrun-{uuid.uuid4().hex[:12]}"
        
        # Persist stdout/stderr as durable artifacts
        tmp_dir = tempfile.mkdtemp(prefix="vrun_", dir=os.path.dirname(self._path) if self._path else None)
        stdout_path = os.path.join(tmp_dir, "stdout.txt")
        stderr_path = os.path.join(tmp_dir, "stderr.txt")
        with open(stdout_path, "w") as f:
            f.write(stdout)
        with open(stderr_path, "w") as f:
            f.write(stderr)
        
        arts = list(artifacts or [])
        # Stamp producer_run_id on each artifact before fingerprinting
        # so the registry is the source of truth for producer linkage
        for a in arts:
            a.producer_run_id = run_id
        record = RunRecord(
            run_id=run_id,
            command=command,
            exit_code=exit_code,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            started_at=started_at,
            finished_at=finished_at,
            artifact_ids=[a.artifact_id for a in arts],
            artifact_fingerprints={
                a.artifact_id: {
                    "content_hash": a.content_hash,
                    "path": a.path,
                    "type": a.type.value,
                    "immutable": a.immutable,
                    "created_at": a.created_at,
                    "producer_run_id": a.producer_run_id,
                }
                for a in arts
            },
        )
        self._records[run_id] = record
        if self._path:
            self._save()
        return record
    
    def get(self, run_id: str) -> RunRecord | None:
        return self._records.get(run_id)
    
    def verify_provenance(
        self,
        run_id: str,
        expected_command: str,
        artifact: ArtifactRef,
    ) -> bool:
        """Authoritative provenance check.
        
        Returns True iff:
        1. Run exists in registry
        2. Run command matches expected_command
        3. Artifact ID is listed in run's artifact_ids
        4. Artifact content_hash matches the hash recorded at run time
           (prevents artifact_id collision/substitution attacks)
        5. Artifact file on disk verifies against its recorded hash
        """
        record = self._records.get(run_id)
        if record is None:
            return False
        if record.command != expected_command:
            return False
        if artifact.artifact_id not in record.artifact_ids:
            return False
        # Full fingerprint binding: content_hash + path + type + immutable
        # must all match the values recorded at run time.
        # This closes same-ID + same-hash substitution with changed metadata.
        recorded_fp = record.artifact_fingerprints.get(artifact.artifact_id)
        if recorded_fp is None:
            return False
        if recorded_fp["content_hash"] != artifact.content_hash:
            return False
        if recorded_fp["path"] != artifact.path:
            return False
        if recorded_fp["type"] != artifact.type.value:
            return False
        if recorded_fp["immutable"] != artifact.immutable:
            return False
        if recorded_fp["created_at"] != artifact.created_at:
            return False
        if recorded_fp.get("producer_run_id") != artifact.producer_run_id:
            return False
        # Integrity: file on disk must still match its hash
        if not artifact.verify_integrity():
            return False
        return True
    
    def _save(self) -> None:
        data = {
            rid: {
                "run_id": r.run_id,
                "command": r.command,
                "exit_code": r.exit_code,
                "stdout_path": r.stdout_path,
                "stderr_path": r.stderr_path,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "artifact_ids": list(r.artifact_ids),
                "artifact_fingerprints": {
                    k: dict(v) for k, v in r.artifact_fingerprints.items()
                },
            }
            for rid, r in self._records.items()
        }
        # Atomic write
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._path)
    
    def _load(self) -> None:
        with open(self._path, "r") as f:
            data = json.load(f)
        self._records = {
            rid: RunRecord(**r_data) for rid, r_data in data.items()
        }
    
    def count(self) -> int:
        return len(self._records)
