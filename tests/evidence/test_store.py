from crucible.evidence.store import EvidenceManifest, EvidenceStore
from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket


def test_store_roundtrip_failure_packet(tmp_path):
    store = EvidenceStore(tmp_path)
    packet = FailureEvidencePacket(
        failure_class=FailureClass.VALIDATION_FAILURE,
        attempt_id="task-1-attempt-1",
        criterion="tests::unit",
        human_summary="unit test failed",
    )
    store.store_evidence_packet(packet)
    loaded = store.load_evidence_packet("task-1-attempt-1")
    assert loaded is not None
    assert loaded.failure_class == FailureClass.VALIDATION_FAILURE
    assert loaded.human_summary == "unit test failed"


def test_store_roundtrip_manifest(tmp_path):
    store = EvidenceStore(tmp_path)
    manifest = EvidenceManifest(attempt_id="task-1-attempt-2")
    manifest.add_artifact("src/foo.py")
    manifest.add_log("pytest.log")
    manifest.review_verdict = "accept"
    store.store_manifest(manifest)
    loaded = store.load_manifest("task-1-attempt-2")
    assert loaded is not None
    assert loaded.review_verdict == "accept"
    assert "src/foo.py" in loaded.evidence_refs
    assert "pytest.log" in loaded.evidence_refs
