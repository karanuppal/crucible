"""
Tests for attempt type enums.

Phase 1: Attempt State Machine & Data Models
"""

import pytest

from crucible.state.attempt_type import AttemptType


class TestAttemptType:
    """Test AttemptType enum and class methods."""
    
    def test_all_types_defined(self):
        """All expected attempt types are defined."""
        expected_types = {
            "build",
            "repair",
            "debug",
            "review",
            "salvage",
            "integrate",
            "revalidate",
        }
        actual_types = {t.value for t in AttemptType}
        assert actual_types == expected_types
    
    def test_implementation_types(self):
        """Implementation types produce artifacts."""
        impl = AttemptType.implementation_types()
        assert AttemptType.BUILD in impl
        assert AttemptType.REPAIR in impl
        assert AttemptType.DEBUG in impl
        assert AttemptType.SALVAGE in impl
        
        # Validation types are not implementation
        assert AttemptType.REVIEW not in impl
        assert AttemptType.REVALIDATE not in impl
    
    def test_validation_types(self):
        """Validation types check artifacts."""
        val = AttemptType.validation_types()
        assert AttemptType.REVIEW in val
        assert AttemptType.REVALIDATE in val
        
        # Implementation types are not validation
        assert AttemptType.BUILD not in val
        assert AttemptType.REPAIR not in val
    
    def test_is_implementation(self):
        """is_implementation returns correct boolean."""
        assert AttemptType.is_implementation(AttemptType.BUILD) is True
        assert AttemptType.is_implementation(AttemptType.REPAIR) is True
        assert AttemptType.is_implementation(AttemptType.REVIEW) is False
        assert AttemptType.is_implementation(AttemptType.INTEGRATE) is True
    
    def test_is_validation(self):
        """is_validation returns correct boolean."""
        assert AttemptType.is_validation(AttemptType.REVIEW) is True
        assert AttemptType.is_validation(AttemptType.REVALIDATE) is True
        assert AttemptType.is_validation(AttemptType.BUILD) is False
        assert AttemptType.is_validation(AttemptType.REPAIR) is False
    
    def test_types_are_disjoint(self):
        """Implementation and validation types have no overlap."""
        impl = AttemptType.implementation_types()
        val = AttemptType.validation_types()
        assert impl.isdisjoint(val)
    
    def test_all_types_covered(self):
        """Every type is either implementation or validation."""
        all_types = set(AttemptType)
        impl = AttemptType.implementation_types()
        val = AttemptType.validation_types()
        covered = impl.union(val)
        assert covered == all_types