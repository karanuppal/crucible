"""Failures module for Crucible v5.4."""

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.failures.next_action_selector import (
    NextAction,
    NextActionDecision,
    NextActionSelector,
)

__all__ = [
    "FailureClass",
    "FailureEvidencePacket",
    "NextAction",
    "NextActionDecision",
    "NextActionSelector",
]