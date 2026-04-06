"""Phase 1 validation: Ledger tests.

Validation matrix requirements:
- Append sequence with stable order and re-read consistency
- Duplicate event ingestion (should append, not deduplicate)
- Corrupted tail record recovery
- Append-only invariant: no update/delete
"""

import json
import os
import tempfile
import time

import pytest

from agentic_harness.ledger.ledger import Ledger, LedgerEvent, EventType


@pytest.fixture
def ledger_path(tmp_path):
    return str(tmp_path / "test-ledger.jsonl")


@pytest.fixture
def ledger(ledger_path):
    return Ledger(ledger_path)


class TestAppendAndRead:
    """Positive path: append events and read them back."""

    def test_append_single_event(self, ledger):
        event = ledger.create_event("proj-1", "build-1", EventType.SPEC_CREATED, {"title": "v1"})
        assert ledger.count == 1
        assert ledger.events()[0].eventType == EventType.SPEC_CREATED

    def test_append_preserves_order(self, ledger):
        for i in range(5):
            ledger.create_event("proj-1", "build-1", EventType.TASK_CREATED, {"index": i})
        events = ledger.events()
        assert len(events) == 5
        for i, e in enumerate(events):
            assert e.payload["index"] == i

    def test_reread_after_reload(self, ledger_path):
        ledger1 = Ledger(ledger_path)
        ledger1.create_event("proj-1", "build-1", EventType.SPEC_CREATED)
        ledger1.create_event("proj-1", "build-1", EventType.TASK_CREATED, {"n": 1})
        ledger1.create_event("proj-1", "build-1", EventType.RUN_SPAWNED, {"n": 2})

        # Reload from disk
        ledger2 = Ledger(ledger_path)
        assert ledger2.count == 3
        assert ledger2.events()[0].eventType == EventType.SPEC_CREATED
        assert ledger2.events()[2].payload["n"] == 2

    def test_events_have_unique_ids(self, ledger):
        e1 = ledger.create_event("proj-1", "build-1", EventType.SPEC_CREATED)
        e2 = ledger.create_event("proj-1", "build-1", EventType.TASK_CREATED)
        assert e1.eventId != e2.eventId


class TestFilterMethods:
    """Filtering by type, task, run."""

    def test_filter_by_type(self, ledger):
        ledger.create_event("p", "b", EventType.SPEC_CREATED)
        ledger.create_event("p", "b", EventType.TASK_CREATED)
        ledger.create_event("p", "b", EventType.TASK_CREATED)
        assert len(ledger.events_by_type(EventType.TASK_CREATED)) == 2

    def test_filter_by_task(self, ledger):
        ledger.create_event("p", "b", EventType.RUN_SPAWNED, task_id="t1")
        ledger.create_event("p", "b", EventType.RUN_SPAWNED, task_id="t2")
        ledger.create_event("p", "b", EventType.RUN_PROGRESS, task_id="t1")
        assert len(ledger.events_for_task("t1")) == 2

    def test_filter_by_run(self, ledger):
        ledger.create_event("p", "b", EventType.RUN_SPAWNED, run_id="r1")
        ledger.create_event("p", "b", EventType.RUN_PROGRESS, run_id="r1")
        ledger.create_event("p", "b", EventType.RUN_KILLED, run_id="r2")
        assert len(ledger.events_for_run("r1")) == 2


class TestDuplicateIngestion:
    """Duplicate events should be appended, not deduplicated."""

    def test_duplicate_payload_appended(self, ledger):
        payload = {"title": "same"}
        ledger.create_event("p", "b", EventType.SPEC_CREATED, payload)
        ledger.create_event("p", "b", EventType.SPEC_CREATED, payload)
        assert ledger.count == 2


class TestCorruptedTailRecovery:
    """Corrupted tail records should be skipped; valid events preserved."""

    def test_corrupted_tail_skipped(self, ledger_path):
        # Write valid events then corrupt the tail
        ledger = Ledger(ledger_path)
        ledger.create_event("p", "b", EventType.SPEC_CREATED, {"valid": True})
        ledger.create_event("p", "b", EventType.TASK_CREATED, {"valid": True})

        # Append corrupted line
        with open(ledger_path, "a") as f:
            f.write("THIS IS NOT JSON\n")

        # Reload — should recover the 2 valid events
        recovered = Ledger(ledger_path)
        assert recovered.count == 2
        assert recovered.events()[0].payload["valid"] is True

    def test_corrupted_middle_skipped(self, ledger_path):
        # Write 3 valid events with corruption in the middle
        ledger = Ledger(ledger_path)
        ledger.create_event("p", "b", EventType.SPEC_CREATED, {"i": 0})
        # Manually inject corruption
        with open(ledger_path, "a") as f:
            f.write("{bad json\n")
        ledger2 = Ledger(ledger_path)
        ledger2.create_event("p", "b", EventType.TASK_CREATED, {"i": 2})
        
        # Reload and verify
        ledger3 = Ledger(ledger_path)
        # Should have event 0 + event 2, corruption skipped
        assert ledger3.count >= 2

    def test_empty_file(self, ledger_path):
        # Create empty file
        with open(ledger_path, "w") as f:
            f.write("")
        ledger = Ledger(ledger_path)
        assert ledger.count == 0

    def test_only_corrupted_lines(self, ledger_path):
        with open(ledger_path, "w") as f:
            f.write("not json\n")
            f.write("also not json\n")
        ledger = Ledger(ledger_path)
        assert ledger.count == 0


class TestAppendOnlyInvariant:
    """The ledger must be append-only: no update, delete, or overwrite."""

    def test_no_public_delete_method(self, ledger):
        assert not hasattr(ledger, "delete")
        assert not hasattr(ledger, "remove")
        assert not hasattr(ledger, "update")
        assert not hasattr(ledger, "overwrite")

    def test_events_list_is_copy(self, ledger):
        ledger.create_event("p", "b", EventType.SPEC_CREATED)
        events = ledger.events()
        events.clear()
        # Internal state not affected
        assert ledger.count == 1

    def test_append_only_grows(self, ledger):
        for i in range(10):
            ledger.create_event("p", "b", EventType.TASK_CREATED, {"i": i})
            assert ledger.count == i + 1
