from crucible.runtime.status_emitter import EventType, StatusEmitter


def test_status_emitter_supports_v54_event_family():
    emitter = StatusEmitter()
    emitter.emit_event(EventType.WORKSPACE_CREATED, "t1", attempt_id="a1", workspace_id="ws-1")
    emitter.emit_event(EventType.FAILURE_PACKET_CREATED, "t1", attempt_id="a1", failure_class="validation_failure")
    emitter.emit_event(EventType.NEXT_ACTION_SELECTED, "t1", attempt_id="a1", action="repair")
    events = emitter.get_events()
    assert [e.event_type for e in events] == [
        EventType.WORKSPACE_CREATED,
        EventType.FAILURE_PACKET_CREATED,
        EventType.NEXT_ACTION_SELECTED,
    ]


def test_status_event_to_message_for_next_action():
    emitter = StatusEmitter()
    emitter.emit_event(EventType.NEXT_ACTION_SELECTED, "t1", action="repair")
    assert "repair" in emitter.get_events()[0].to_message()
