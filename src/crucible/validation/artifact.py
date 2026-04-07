"""Phase 3: Artifact reference model.

Spec §11: Artifacts must be immutable and typed.
Execution Plan: every criterion must link to at least one artifact with verifiable reachability.

An ArtifactRef is a durable, content-addressed pointer to a file or blob
produced during a run. Validation MUST NOT accept narrative strings as evidence —
only ArtifactRefs that can be reached and verified.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class ArtifactType(str, Enum):
    FILE = "file"
    LOG = "log"
    TEST_REPORT = "test_report"
    DIFF = "diff"
    COMMAND_OUTPUT = "command_output"
    REVIEWER_REPORT = "reviewer_report"
    SPEC = "spec"


@dataclass
class ArtifactRef:
    """Durable, content-hashed pointer to an artifact."""
    artifact_id: str
    type: ArtifactType
    path: str
    content_hash: str
    producer_run_id: str
    created_at: float
    immutable: bool = True
    
    def exists(self) -> bool:
        """Check that the artifact is actually reachable on disk."""
        return os.path.isfile(self.path)
    
    def verify_integrity(self) -> bool:
        """Recompute hash and compare. Returns True if hash matches."""
        if not self.exists():
            return False
        return compute_file_hash(self.path) == self.content_hash
    
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        return d
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRef":
        return cls(
            artifact_id=data["artifact_id"],
            type=ArtifactType(data["type"]),
            path=data["path"],
            content_hash=data["content_hash"],
            producer_run_id=data["producer_run_id"],
            created_at=data["created_at"],
            immutable=data.get("immutable", True),
        )


def compute_file_hash(path: str) -> str:
    """Compute sha256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def create_artifact_ref(
    path: str,
    artifact_type: ArtifactType,
    producer_run_id: str,
    artifact_id: str | None = None,
) -> ArtifactRef:
    """Create an artifact ref from a real file on disk.
    
    Raises FileNotFoundError if the file doesn't exist — enforces
    that artifact refs can only be created for real artifacts.
    """
    import time
    import uuid
    
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Cannot create artifact ref: {path} does not exist")
    
    content_hash = compute_file_hash(path)
    return ArtifactRef(
        artifact_id=artifact_id or f"art-{uuid.uuid4().hex[:8]}",
        type=artifact_type,
        path=path,
        content_hash=content_hash,
        producer_run_id=producer_run_id,
        created_at=time.time(),
        immutable=True,
    )
