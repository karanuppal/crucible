"""Failure evidence packet for Crucible v6.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class FailureClass(str, Enum):
    RETRYABLE = "retryable"
    NEEDS_USER_INPUT = "needs_user_input"
    STUCK_OR_REPEATING = "stuck_or_repeating"
    TERMINAL_NONRECOVERABLE = "terminal_nonrecoverable"


@dataclass
class FailureEvidencePacket:
    """Structured, durable failure evidence consumed by policy code.

    v6.1 keeps the top-level control plane intentionally thin and pushes
    specificity into evidence, hints, metadata, and attempt history.
    """

    failure_class: FailureClass
    attempt_id: str
    criterion: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    reproducible: bool = True
    error_message: str | None = None
    root_cause_hypothesis: str | None = None
    prior_attempts: list[str] = field(default_factory=list)

    task_id: str | None = None
    signature: str | None = None
    human_summary: str = ""
    machine_action: str = ""
    consumes_budget: bool = True
    recommended_next_roles: list[str] = field(default_factory=list)
    failing_command: str | None = None
    missing_artifacts: list[str] = field(default_factory=list)
    recent_lane: str | None = None
    hints: list[str] = field(default_factory=list)
    progress_made: bool = False
    repeated_failure: bool = False
    external_input_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.attempt_id:
            raise ValueError("attempt_id is required")
        if self.task_id is None:
            self.task_id = self._infer_task_id()
        if self.signature is None:
            self.signature = self.compute_signature()
        if not self.human_summary:
            self.human_summary = self._default_human_summary()
        if not self.machine_action:
            self.machine_action = self.failure_class.value
        if not self.recommended_next_roles:
            self.recommended_next_roles = self._default_roles()

    def _infer_task_id(self) -> str | None:
        if "-attempt-" in self.attempt_id:
            return self.attempt_id.split("-attempt-", 1)[0]
        return None

    def _default_human_summary(self) -> str:
        parts = [self.failure_class.value]
        if self.criterion:
            parts.append(f"criterion={self.criterion}")
        if self.hints:
            parts.append(f"hints={','.join(sorted(self.hints))}")
        if self.error_message:
            parts.append(self.error_message)
        return "; ".join(parts)

    def _default_roles(self) -> list[str]:
        mapping = {
            FailureClass.RETRYABLE: ["builder"],
            FailureClass.NEEDS_USER_INPUT: ["user"],
            FailureClass.STUCK_OR_REPEATING: ["debugger"],
            FailureClass.TERMINAL_NONRECOVERABLE: ["user", "reviewer"],
        }
        return mapping[self.failure_class]

    def compute_signature(self) -> str:
        criterion = self.criterion or "-"
        cmd = self.failing_command or "-"
        lane = self.recent_lane or "-"
        artifact_shape = ",".join(sorted(self.missing_artifacts)) or "-"
        evidence_shape = ",".join(sorted(self.evidence_refs)) or "-"
        hint_shape = ",".join(sorted(self.hints)) or "-"
        return "|".join([
            self.failure_class.value,
            criterion,
            cmd,
            artifact_shape,
            lane,
            evidence_shape,
            hint_shape,
        ])

    def to_next_action_input(self) -> dict[str, Any]:
        return {
            "failure_class": self.failure_class,
            "attempt_id": self.attempt_id,
            "task_id": self.task_id,
            "criterion": self.criterion,
            "evidence_refs": list(self.evidence_refs),
            "reproducible": self.reproducible,
            "prior_attempts": list(self.prior_attempts),
            "root_cause_known": self.root_cause_hypothesis is not None,
            "signature": self.signature,
            "machine_action": self.machine_action,
            "consumes_budget": self.consumes_budget,
            "recommended_next_roles": list(self.recommended_next_roles),
            "recent_lane": self.recent_lane,
            "hints": list(self.hints),
            "progress_made": self.progress_made,
            "repeated_failure": self.repeated_failure,
            "external_input_required": self.external_input_required,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_class": self.failure_class.value,
            "attempt_id": self.attempt_id,
            "task_id": self.task_id,
            "criterion": self.criterion,
            "evidence_refs": list(self.evidence_refs),
            "timestamp": self.timestamp.isoformat(),
            "reproducible": self.reproducible,
            "error_message": self.error_message,
            "root_cause_hypothesis": self.root_cause_hypothesis,
            "prior_attempts": list(self.prior_attempts),
            "signature": self.signature,
            "human_summary": self.human_summary,
            "machine_action": self.machine_action,
            "consumes_budget": self.consumes_budget,
            "recommended_next_roles": list(self.recommended_next_roles),
            "failing_command": self.failing_command,
            "missing_artifacts": list(self.missing_artifacts),
            "recent_lane": self.recent_lane,
            "hints": list(self.hints),
            "progress_made": self.progress_made,
            "repeated_failure": self.repeated_failure,
            "external_input_required": self.external_input_required,
            "metadata": dict(self.metadata),
        }
