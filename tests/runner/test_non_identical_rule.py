"""
Tests for non-identical retry rule.

Phase 3: Role Handoff Controller
"""

import pytest

from crucible.runner.non_identical_rule import AttemptSignature, NonIdenticalRetryRule


class TestAttemptSignature:
    """Test AttemptSignature."""
    
    def test_creation(self):
        """Can create signature."""
        sig = AttemptSignature(
            prompt="fix the bug",
            role="builder",
            backend="codex",
        )
        
        assert sig.prompt == "fix the bug"
        assert sig.role == "builder"
        assert sig.backend == "codex"
    
    def test_equality(self):
        """Equality comparison works."""
        sig1 = AttemptSignature(prompt="test", role="builder")
        sig2 = AttemptSignature(prompt="test", role="builder")
        sig3 = AttemptSignature(prompt="different", role="builder")
        
        assert sig1 == sig2
        assert sig1 != sig3
    
    def test_hash(self):
        """Hash works for set membership."""
        sig1 = AttemptSignature(prompt="test", role="builder")
        sig2 = AttemptSignature(prompt="test", role="builder")
        
        s = {sig1, sig2}
        assert len(s) == 1  # Same hash, same content


class TestNonIdenticalRetryRule:
    """Test NonIdenticalRetryRule."""
    
    def test_first_attempt_allowed(self):
        """First attempt always allowed."""
        rule = NonIdenticalRetryRule()
        sig = AttemptSignature(prompt="first", role="builder")
        
        allowed, reason = rule.is_allowed(sig)
        
        assert allowed is True
        assert reason == "first attempt"
    
    def test_identical_retry_blocked(self):
        """Identical retry is blocked."""
        rule = NonIdenticalRetryRule()
        sig = AttemptSignature(prompt="fix", role="builder")
        
        rule.record_attempt(sig)
        allowed, reason = rule.is_allowed(sig)
        
        assert allowed is False
        assert "identical" in reason
    
    def test_different_prompt_allowed(self):
        """Different prompt is allowed."""
        rule = NonIdenticalRetryRule()
        sig1 = AttemptSignature(prompt="fix v1", role="builder")
        sig2 = AttemptSignature(prompt="fix v2", role="builder")
        
        rule.record_attempt(sig1)
        allowed, reason = rule.is_allowed(sig2)
        
        assert allowed is True
        assert "meaningful change" in reason
    
    def test_different_role_allowed(self):
        """Different role is allowed."""
        rule = NonIdenticalRetryRule()
        sig1 = AttemptSignature(prompt="fix", role="builder")
        sig2 = AttemptSignature(prompt="fix", role="debugger")
        
        rule.record_attempt(sig1)
        allowed, reason = rule.is_allowed(sig2)
        
        assert allowed is True
    
    def test_different_backend_allowed(self):
        """Different backend is allowed."""
        rule = NonIdenticalRetryRule()
        sig1 = AttemptSignature(prompt="fix", role="builder", backend="codex")
        sig2 = AttemptSignature(prompt="fix", role="builder", backend="opus")
        
        rule.record_attempt(sig1)
        allowed, reason = rule.is_allowed(sig2)
        
        assert allowed is True
    
    def test_different_workspace_allowed(self):
        """Different workspace basis is allowed."""
        rule = NonIdenticalRetryRule()
        sig1 = AttemptSignature(prompt="fix", role="builder", workspace_basis="ws1")
        sig2 = AttemptSignature(prompt="fix", role="builder", workspace_basis="ws2")
        
        rule.record_attempt(sig1)
        allowed, reason = rule.is_allowed(sig2)
        
        assert allowed is True
    
    def test_different_evidence_allowed(self):
        """Different evidence refs are allowed."""
        rule = NonIdenticalRetryRule()
        sig1 = AttemptSignature(prompt="fix", role="builder", evidence_refs=("e1",))
        sig2 = AttemptSignature(prompt="fix", role="builder", evidence_refs=("e2",))
        
        rule.record_attempt(sig1)
        allowed, reason = rule.is_allowed(sig2)
        
        assert allowed is True
    
    def test_no_change_blocked(self):
        """No meaningful change is blocked."""
        rule = NonIdenticalRetryRule()
        sig1 = AttemptSignature(prompt="fix", role="builder")
        sig2 = AttemptSignature(prompt="fix", role="builder")
        
        rule.record_attempt(sig1)
        allowed, reason = rule.is_allowed(sig2)
        
        assert allowed is False
        # Either identical or no meaningful change
        assert "identical" in reason or "no meaningful change" in reason
    
    def test_multiple_signatures_tracked(self):
        """Multiple signatures are tracked."""
        rule = NonIdenticalRetryRule()
        sig1 = AttemptSignature(prompt="fix v1", role="builder")
        sig2 = AttemptSignature(prompt="fix v2", role="builder")
        sig3 = AttemptSignature(prompt="fix v3", role="builder")
        
        rule.record_attempt(sig1)
        rule.record_attempt(sig2)
        
        assert rule.get_signature_count() == 2
        
        allowed, _ = rule.is_allowed(sig3)
        assert allowed is True  # Different from both
    
    def test_clear_resets(self):
        """clear resets all signatures."""
        rule = NonIdenticalRetryRule()
        sig = AttemptSignature(prompt="fix", role="builder")
        
        rule.record_attempt(sig)
        assert rule.get_signature_count() == 1
        
        rule.clear()
        assert rule.get_signature_count() == 0
    
    def test_get_previous_signatures(self):
        """get_previous_signatures returns copy."""
        rule = NonIdenticalRetryRule()
        sig = AttemptSignature(prompt="fix", role="builder")
        
        rule.record_attempt(sig)
        signatures = rule.get_previous_signatures()
        
        assert len(signatures) == 1
        assert signatures[0].prompt == "fix"