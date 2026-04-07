"""
Role executor for Crucible v5.4.

Spawns appropriate worker based on attempt type.
"""

from dataclasses import dataclass
from typing import Any, Optional

from crucible.runner.handoff_controller import HandoffController, Role
from crucible.state.attempt_type import AttemptType


@dataclass
class RoleExecutorConfig:
    """Configuration for role executor."""
    
    # Backend to use for each role
    builder_backend: str = "codex"
    debugger_backend: str = "codex"
    reviewer_backend: str = "opus"
    salvage_backend: str = "codex"
    integrator_backend: str = "codex"
    
    # Timeout per role (seconds)
    builder_timeout: int = 300
    debugger_timeout: int = 300
    reviewer_timeout: int = 180
    salvage_timeout: int = 180
    integrator_timeout: int = 180


class RoleExecutor:
    """
    Executes work using appropriate role/backend for attempt type.
    
    This is the runtime interface that actually spawns workers.
    """
    
    def __init__(self, config: Optional[RoleExecutorConfig] = None):
        """Initialize executor with config."""
        self.config = config or RoleExecutorConfig()
    
    def get_backend_for_attempt(self, attempt_type: AttemptType) -> str:
        """Get backend for attempt type."""
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
        """Get timeout for attempt type."""
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
        """Get role for attempt type."""
        return HandoffController.get_role_for_attempt_type(attempt_type)
    
    def get_prompt_for_attempt(
        self,
        attempt_type: AttemptType,
        context: dict[str, Any],
    ) -> str:
        """
        Generate prompt for attempt type.
        
        This would be the actual prompt sent to the worker.
        """
        role = self.get_role_for_attempt(attempt_type)
        
        if attempt_type == AttemptType.BUILD:
            return self._build_builder_prompt(context)
        elif attempt_type == AttemptType.REPAIR:
            return self._build_repair_prompt(context)
        elif attempt_type == AttemptType.DEBUG:
            return self._build_debugger_prompt(context)
        elif attempt_type == AttemptType.REVIEW:
            return self._build_reviewer_prompt(context)
        elif attempt_type == AttemptType.SALVAGE:
            return self._build_salvage_prompt(context)
        elif attempt_type == AttemptType.INTEGRATE:
            return self._build_integrator_prompt(context)
        elif attempt_type == AttemptType.REVALIDATE:
            return self._build_revalidator_prompt(context)
        
        return "Complete the task."
    
    def _build_builder_prompt(self, context: dict) -> str:
        """Build prompt for builder."""
        spec = context.get("spec", "No spec provided")
        return f"Implement the following specification:\n\n{spec}"
    
    def _build_repair_prompt(self, context: dict) -> str:
        """Build prompt for repair."""
        failure = context.get("failure_evidence", "Unknown failure")
        evidence = context.get("evidence_refs", [])
        evidence_text = "\n".join(f"- {e}" for e in evidence) if evidence else "No evidence"
        return f"Fix the following failure:\n{failure}\n\nEvidence:\n{evidence_text}"
    
    def _build_debugger_prompt(self, context: dict) -> str:
        """Build prompt for debugger."""
        failure = context.get("failure_evidence", "Unknown failure")
        prior_attempts = context.get("prior_attempts", [])
        prior_text = "\n".join(f"- {a}" for a in prior_attempts) if prior_attempts else "No prior attempts"
        return f"Debug the following failure. Root cause is unclear:\n{failure}\n\nPrior attempts:\n{prior_text}"
    
    def _build_reviewer_prompt(self, context: dict) -> str:
        """Build prompt for reviewer."""
        output = context.get("output", "No output provided")
        criteria = context.get("criteria", [])
        criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "No criteria"
        return f"Review the following output against these criteria:\n{criteria_text}\n\nOutput:\n{output}"
    
    def _build_salvage_prompt(self, context: dict) -> str:
        """Build prompt for salvage."""
        partial = context.get("partial_artifacts", [])
        partial_text = "\n".join(f"- {p}" for p in partial) if partial else "No partial artifacts"
        return f"Salvage useful work from partial artifacts:\n{partial_text}"
    
    def _build_integrator_prompt(self, context: dict) -> str:
        """Build prompt for integrator."""
        outputs = context.get("outputs", [])
        outputs_text = "\n".join(f"- {o}" for o in outputs) if outputs else "No outputs"
        return f"Integrate the following outputs:\n{outputs_text}"
    
    def _build_revalidator_prompt(self, context: dict) -> str:
        """Build prompt for revalidator."""
        modified = context.get("modified_artifacts", [])
        criteria = context.get("criteria", [])
        criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "No criteria"
        modified_text = "\n".join(f"- {m}" for m in modified) if modified else "No artifacts"
        return f"Revalidate modified artifacts against criteria:\n{criteria_text}\n\nModified:\n{modified_text}"