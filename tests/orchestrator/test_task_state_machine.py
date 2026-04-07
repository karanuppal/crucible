from crucible.orchestrator.task_state_machine import TaskStateMachine


def test_happy_path_transitions():
    machine = TaskStateMachine()
    state = "queued"
    state = machine.transition(state, "start_build")
    state = machine.transition(state, "start_validation")
    state = machine.transition(state, "validation_passed")
    state = machine.transition(state, "review_accepted")
    assert state == "complete"
    assert machine.is_terminal(state)


def test_failure_path_to_repair_then_complete():
    machine = TaskStateMachine()
    state = "queued"
    for event in ["start_build", "start_validation", "validation_failed_repair", "start_validation", "validation_passed", "review_accepted"]:
        state = machine.transition(state, event)
    assert state == "complete"


def test_illegal_transition_raises():
    machine = TaskStateMachine()
    try:
        machine.transition("queued", "review_accepted")
    except ValueError as exc:
        assert "illegal transition" in str(exc)
    else:
        raise AssertionError("expected ValueError")
