"""
Role executor for Crucible v6.1.

Spawns appropriate worker based on attempt type and shapes recovery prompts
according to the v6.1 prompt contract.
"""

from dataclasses import dataclass
from typing import Any, Optional

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.runner.handoff_controller import HandoffController, Role
from crucible.state.attempt_type import AttemptType


@dataclass
class RoleExecutorConfig:
    """Configuration for role executor."""

    builder_backend: str = "codex"
    debugger_backend: str = "codex"
    reviewer_backend: str = "opus"
    salvage_backend: str = "codex"
    integrator_backend: str = "codex"

    builder_timeout: int = 300
    debugger_timeout: int = 300
    reviewer_timeout: int = 180
    salvage_timeout: int = 180
    integrator_timeout: int = 180


class RoleExecutor:
    """Executes work using the appropriate role/backend for an attempt type."""

    def __init__(self, config: Optional[RoleExecutorConfig] = None):
        self.config = config or RoleExecutorConfig()

    def get_backend_for_attempt(self, attempt_type: AttemptType) -> str:
        mapping = {
            AttemptType.BUILD: self.config.builder_backend,
            AttemptType.REPAIR: self.config.builder_backend,
            AttemptType.DEBUG: self.config.debugger_backend,
            AttemptType.REVIEW: self.config.reviewer_backend,
            AttemptType.SALVAGE: self.config.salvage_backend,
            AttemptType.INTEGRATE: self.config.integrator_backend,
            AttemptType.REVALIDATE: self.config.reviewer_backend,
        }
        return mapping.get(attempt_type, self.config.builder_backend)

    def get_timeout_for_attempt(self, attempt_type: AttemptType) -> int:
        mapping = {
            AttemptType.BUILD: self.config.builder_timeout,
            AttemptType.REPAIR: self.config.builder_timeout,
            AttemptType.DEBUG: self.config.debugger_timeout,
            AttemptType.REVIEW: self.config.reviewer_timeout,
            AttemptType.SALVAGE: self.config.salvage_timeout,
            AttemptType.INTEGRATE: self.config.integrator_timeout,
            AttemptType.REVALIDATE: self.config.reviewer_timeout,
        }
        return mapping.get(attempt_type, self.config.builder_timeout)

    def get_role_for_attempt(self, attempt_type: AttemptType) -> Role:
        return HandoffController.get_role_for_attempt_type(attempt_type)

    def get_prompt_for_attempt(self, attempt_type: AttemptType, context: dict[str, Any]) -> str:
        if attempt_type == AttemptType.BUILD:
            return self._build_builder_prompt(context)
        if attempt_type == AttemptType.REPAIR:
            return self._build_repair_prompt(context)
        if attempt_type == AttemptType.DEBUG:
            return self._build_debugger_prompt(context)
        if attempt_type == AttemptType.REVIEW:
            return self._build_reviewer_prompt(context)
        if attempt_type == AttemptType.SALVAGE:
            return self._build_salvage_prompt(context)
        if attempt_type == AttemptType.INTEGRATE:
            return self._build_integrator_prompt(context)
        if attempt_type == AttemptType.REVALIDATE:
            return self._build_revalidator_prompt(context)
        return "Complete the task."

    def _build_builder_prompt(self, context: dict[str, Any]) -> str:
        spec = context.get("spec", "No spec provided")
        return f"Implement the following specification:\n\n{spec}"

    def _build_repair_prompt(self, context: dict[str, Any]) -> str:
        return self._build_recovery_prompt(context, mode="repair")

    def _build_debugger_prompt(self, context: dict[str, Any]) -> str:
        return self._build_recovery_prompt(context, mode="debug")

    def _build_recovery_prompt(self, context: dict[str, Any], *, mode: str) -> str:
        failure = self._coerce_failure_evidence(context.get("failure_evidence"))
        task_goal = context.get("task_goal") or context.get("spec") or "No task goal provided"
        current_failure = context.get("current_failure") or self._failure_summary(failure)
        raw_output = context.get("raw_command_output") or context.get("command_output")
        if not raw_output and failure is not None:
            raw_output = failure.error_message
        if not raw_output:
            raw_output = "No raw command output captured"
        evidence_packet = self._format_evidence_packet(failure, context)
        prior_summary = self._format_prior_attempts_summary(context)

        lines = [
            f"Recovery mode: {mode}",
            "",
            "Task goal:",
            str(task_goal),
            "",
            "Current failure:",
            current_failure,
            "",
            "Raw command output:",
            str(raw_output),
            "",
            "Structured evidence packet:",
            evidence_packet,
            "",
            "Prior attempts summary:",
            prior_summary,
            "",
        ]

        if failure and (failure.failure_class == FailureClass.STUCK_OR_REPEATING or failure.repeated_failure):
            lines.extend([
                "This run is classified as stuck_or_repeating.",
                "You must summarize the prior failed approaches before doing anything else.",
                "You must try a materially different strategy than prior attempts; do not repeat shallow variants of the same fix.",
                "Prefer changing approach, search path, tooling, framing, worker/backend, or workspace basis if available.",
                "",
            ])

        lines.extend([
            "After making a fix, explicitly verify it with the relevant command(s) and report whether verification passed.",
            "Do not claim success without verification.",
        ])
        return "\n".join(lines)

    def _coerce_failure_evidence(self, value: Any) -> FailureEvidencePacket | None:
        return value if isinstance(value, FailureEvidencePacket) else None

    def _failure_summary(self, failure: FailureEvidencePacket | None) -> str:
        if failure is None:
            return "Unknown failure"
        parts = [failure.human_summary or failure.failure_class.value]
        if failure.root_cause_hypothesis:
            parts.append(f"Root cause hypothesis: {failure.root_cause_hypothesis}")
        if failure.failing_command:
            parts.append(f"Failing command: {failure.failing_command}")
        return "\n".join(parts)

    def _format_evidence_packet(self, failure: FailureEvidencePacket | None, context: dict[str, Any]) -> str:
        packet = failure.to_dict() if failure is not None else {
            "failure_evidence": context.get("failure_evidence", "Unknown failure"),
            "evidence_refs": list(context.get("evidence_refs", [])),
        }
        return "\n".join(f"- {key}: {value}" for key, value in packet.items())

    def _format_prior_attempts_summary(self, context: dict[str, Any]) -> str:
        summary = context.get("prior_attempts_summary")
        if summary:
            return str(summary)
        prior_attempts = context.get("prior_attempts", [])
        if not prior_attempts:
            return "No prior attempts"
        formatted: list[str] = []
        for attempt in prior_attempts:
            if isinstance(attempt, dict):
                attempt_id = attempt.get("attempt_id") or attempt.get("id") or "attempt"
                outcome = attempt.get("outcome") or attempt.get("status") or attempt.get("result") or "unknown"
                approach = attempt.get("approach") or attempt.get("summary") or attempt.get("prompt") or "no approach summary"
                formatted.append(f"- {attempt_id}: {outcome}; {approach}")
            else:
                formatted.append(f"- {attempt}")
        return "\n".join(formatted)

    def _build_reviewer_prompt(self, context: dict[str, Any]) -> str:
        output = context.get("output", "No output provided")
        criteria = context.get("criteria", [])
        criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "No criteria"
        return f"Review the following output against these criteria:\n{criteria_text}\n\nOutput:\n{output}"

    def _build_salvage_prompt(self, context: dict[str, Any]) -> str:
        partial = context.get("partial_artifacts", [])
        partial_text = "\n".join(f"- {p}" for p in partial) if partial else "No partial artifacts"
        return f"Salvage useful work from partial artifacts:\n{partial_text}"

    def _build_integrator_prompt(self, context: dict[str, Any]) -> str:
        outputs = context.get("outputs", [])
        outputs_text = "\n".join(f"- {o}" for o in outputs) if outputs else "No outputs"
        return f"Integrate the following outputs:\n{outputs_text}"

    def _build_revalidator_prompt(self, context: dict[str, Any]) -> str:
        modified = context.get("modified_artifacts", [])
        criteria = context.get("criteria", [])
        criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "No criteria"
        modified_text = "\n".join(f"- {m}" for m in modified) if modified else "No artifacts"
        return f"Revalidate modified artifacts against criteria:\n{criteria_text}\n\nModified:\n{modified_text}"
