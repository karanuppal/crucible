"""Phase 1 adversarial tests: ledger integrity, forgery detection, strict mode."""

import json
import pytest

from crucible.ledger.ledger import Ledger, EventType


class TestLedgerForgeryDetection:
    """Strict mode should detect file replacement and non-tail corruption."""

    def test_strict_rejects_non_tail_corruption(self, tmp_path):
        path = str(tmp_path / "ledger.jsonl")
        ledger = Ledger(path)
        ledger.create_event("p", "b", EventType.SPEC_CREATED, {"i": 0})
        ledger.create_event("p", "b", EventType.TASK_CREATED, {"i": 1})

        # Inject corruption in the middle
        with open(path, "r") as f:
            lines = f.readlines()
        lines.insert(1, "CORRUPTED LINE\n")
        with open(path, "w") as f:
            f.writelines(lines)

        with pytest.raises(ValueError, match="Corrupted non-tail record"):
            Ledger(path, strict_integrity=True)

    def test_strict_allows_tail_corruption(self, tmp_path):
        path = str(tmp_path / "ledger.jsonl")
        ledger = Ledger(path)
        ledger.create_event("p", "b", EventType.SPEC_CREATED)

        with open(path, "a") as f:
            f.write("CORRUPTED TAIL\n")

        # Should NOT raise — tail corruption is allowed
        recovered = Ledger(path, strict_integrity=True)
        assert recovered.count == 1

    def test_sequence_number_detects_rewrite(self, tmp_path):
        path = str(tmp_path / "ledger.jsonl")
        ledger = Ledger(path)
        ledger.create_event("p", "b", EventType.SPEC_CREATED)
        ledger.create_event("p", "b", EventType.TASK_CREATED)

        # Forge file: duplicate seq 0
        with open(path, "r") as f:
            lines = f.readlines()
        data = json.loads(lines[1])
        data["seq"] = 0  # duplicate seq
        lines[1] = json.dumps(data) + "\n"
        with open(path, "w") as f:
            f.writelines(lines)

        with pytest.raises(ValueError, match="Non-monotonic sequence"):
            Ledger(path, strict_integrity=True)

    def test_lenient_mode_still_loads_on_corruption(self, tmp_path):
        path = str(tmp_path / "ledger.jsonl")
        ledger = Ledger(path)
        ledger.create_event("p", "b", EventType.SPEC_CREATED)

        with open(path, "a") as f:
            f.write("BAD LINE\n")

        # Lenient mode should not raise
        recovered = Ledger(path, strict_integrity=False)
        assert recovered.count == 1


class TestSequenceNumbers:
    """Events should have monotonic sequence numbers."""

    def test_events_have_sequence_numbers(self, tmp_path):
        path = str(tmp_path / "ledger.jsonl")
        ledger = Ledger(path)
        ledger.create_event("p", "b", EventType.SPEC_CREATED)
        ledger.create_event("p", "b", EventType.TASK_CREATED)

        with open(path, "r") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert lines[0]["seq"] == 0
        assert lines[1]["seq"] == 1

    def test_sequence_continues_after_reload(self, tmp_path):
        path = str(tmp_path / "ledger.jsonl")
        ledger1 = Ledger(path)
        ledger1.create_event("p", "b", EventType.SPEC_CREATED)
        ledger1.create_event("p", "b", EventType.TASK_CREATED)

        ledger2 = Ledger(path)
        ledger2.create_event("p", "b", EventType.RUN_SPAWNED)

        with open(path, "r") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert lines[2]["seq"] == 2
