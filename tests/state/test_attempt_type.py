"""Tests for attempt type enums."""

from crucible.state.attempt_type import AttemptType


class TestAttemptType:
    def test_all_types_defined(self):
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
        impl = AttemptType.implementation_types()
        assert AttemptType.BUILD in impl
        assert AttemptType.REPAIR in impl
        assert AttemptType.DEBUG in impl
        assert AttemptType.SALVAGE in impl
        assert AttemptType.REVIEW not in impl
        assert AttemptType.REVALIDATE not in impl

    def test_validation_types(self):
        val = AttemptType.validation_types()
        assert AttemptType.REVIEW in val
        assert AttemptType.REVALIDATE in val
        assert AttemptType.BUILD not in val
        assert AttemptType.REPAIR not in val

    def test_llm_capable_types_cover_all_core_roles(self):
        assert AttemptType.llm_capable_types() == set(AttemptType)

    def test_is_implementation(self):
        assert AttemptType.is_implementation(AttemptType.BUILD) is True
        assert AttemptType.is_implementation(AttemptType.REPAIR) is True
        assert AttemptType.is_implementation(AttemptType.REVIEW) is False
        assert AttemptType.is_implementation(AttemptType.INTEGRATE) is True

    def test_is_validation(self):
        assert AttemptType.is_validation(AttemptType.REVIEW) is True
        assert AttemptType.is_validation(AttemptType.REVALIDATE) is True
        assert AttemptType.is_validation(AttemptType.BUILD) is False
        assert AttemptType.is_validation(AttemptType.REPAIR) is False

    def test_types_are_disjoint(self):
        impl = AttemptType.implementation_types()
        val = AttemptType.validation_types()
        assert impl.isdisjoint(val)

    def test_all_types_covered(self):
        all_types = set(AttemptType)
        covered = AttemptType.implementation_types().union(AttemptType.validation_types())
        assert covered == all_types
