"""
Non-identical retry rule for Crucible v5.4.

Enforces: new repair must differ from rejected attempt in prompt/role/backend/workspace/evidence/decomposition.
Blind respawn of same failed shape is prohibited.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class AttemptSignature:
    """
    Signature of an attempt for comparison.
    
    Used to detect identical retries that should be blocked.
    """
    
    prompt: str
    role: str
    backend: Optional[str] = None
    workspace_basis: Optional[str] = None
    evidence_refs: tuple[str, ...] = ()
    decomposition: Optional[str] = None
    
    def __hash__(self):
        """Hash for set membership."""
        return hash((
            self.prompt,
            self.role,
            self.backend,
            self.workspace_basis,
            self.evidence_refs,
            self.decomposition,
        ))
    
    def __eq__(self, other):
        """Equality comparison."""
        if not isinstance(other, AttemptSignature):
            return False
        return (
            self.prompt == other.prompt and
            self.role == other.role and
            self.backend == other.backend and
            self.workspace_basis == other.workspace_basis and
            self.evidence_refs == other.evidence_refs and
            self.decomposition == other.decomposition
        )


class NonIdenticalRetryRule:
    """
    Enforces non-identical retry rule from spec Section 7.4.
    
    A new repair attempt is permitted only if at least one of:
    - prompt or instructions meaningfully change
    - role changes
    - backend or model changes
    - workspace basis changes
    - input evidence set changes
    - decomposition changes
    """
    
    def __init__(self):
        """Initialize tracker."""
        self._previous_signatures: list[AttemptSignature] = []
    
    def record_attempt(self, signature: AttemptSignature):
        """Record an attempt signature for comparison."""
        self._previous_signatures.append(signature)
    
    def is_allowed(self, new_signature: AttemptSignature) -> tuple[bool, str]:
        """
        Check if new attempt is allowed.
        
        Returns:
            (allowed: bool, reason: str)
        """
        # If no previous attempts, always allowed
        if not self._previous_signatures:
            return True, "first attempt"
        
        # Check against all previous signatures
        for prev in self._previous_signatures:
            if self._is_identical(new_signature, prev):
                return False, f"identical to previous attempt (role={prev.role})"
        
        # Check for meaningful change
        last_signature = self._previous_signatures[-1]
        if self._has_meaningful_change(new_signature, last_signature):
            return True, "meaningful change detected"
        
        return False, "no meaningful change from previous attempt"
    
    def _is_identical(self, new: AttemptSignature, prev: AttemptSignature) -> bool:
        """Check if signatures are identical."""
        return new == prev
    
    def _has_meaningful_change(
        self,
        new: AttemptSignature,
        prev: AttemptSignature,
    ) -> bool:
        """Check if there's at least one meaningful change."""
        changes = [
            new.prompt != prev.prompt,
            new.role != prev.role,
            new.backend != prev.backend,
            new.workspace_basis != prev.workspace_basis,
            new.evidence_refs != prev.evidence_refs,
            new.decomposition != prev.decomposition,
        ]
        return any(changes)
    
    def get_previous_signatures(self) -> list[AttemptSignature]:
        """Get all recorded signatures."""
        return self._previous_signatures.copy()
    
    def clear(self):
        """Clear all recorded signatures."""
        self._previous_signatures.clear()
    
    def get_signature_count(self) -> int:
        """Get number of recorded signatures."""
        return len(self._previous_signatures)