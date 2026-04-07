"""
Tests for closed-loop executor.

Phase 4: Closed-Loop Runtime Orchestrator
"""

import pytest

from crucible.orchestrator.closed_loop_executor import (
    AttemptRecord,
    AttemptState,
    AttemptType,
    ClosedLoopExecutor,
    TaskContext,
    TaskStatus,
    WorkspaceLineageType,
    WorkspaceRecord,
)
from crucible.policy.budgets import BudgetPolicy


class TestClosedLoopExecutor:
    """Test ClosedLoopExecutor."""
    
    def test_initialization(self):
        """Executor initializes with defaults."""
        executor = ClosedLoopExecutor()
        
        assert executor.budget_policy is not None
        assert executor.circuit_config is not None
        assert executor.role_executor is not None
    
    def test_initialization_with_custom_policy(self):
        """Executor accepts custom policy."""
        policy = BudgetPolicy(repair_attempt_budget=10)
        executor = ClosedLoopExecutor(budget_policy=policy)
        
        assert executor.budget_policy.repair_attempt_budget == 10
    
    def test_task_context_creation(self):
        """TaskContext creates correctly."""
        ctx = TaskContext(
            task_id="task-1",
            spec="Implement X",
            criteria=["criterion1", "criterion2"],
        )
        
        assert ctx.task_id == "task-1"
        assert ctx.status == TaskStatus.QUEUED
        assert len(ctx.attempts) == 0
    
    def test_task_starts_review_on_first_pass(self):
        """Validated implementation pass schedules a real review attempt."""
        executor = ClosedLoopExecutor()
        
        ctx = TaskContext(
            task_id="task-1",
            spec="Implement X",
            criteria=["criterion1"],
            review_required=True,
        )
        
        # Simulate: run build, then mark as validated_pass
        ctx = executor._start_build(ctx)
        assert ctx.status == TaskStatus.BUILDING
        
        # Initialize the other tracking components
        from crucible.policy.circuit_breaker import CircuitBreaker
        ctx.circuit_breaker = CircuitBreaker(executor.circuit_config)
        
        # Simulate validation pass
        ctx.current_attempt.state = AttemptState.VALIDATED_PASS
        prior_attempt_id = ctx.current_attempt.attempt_id
        ctx = executor._handle_validation_pass(ctx, ctx.current_attempt)

        assert ctx.status == TaskStatus.AWAITING_REVIEW
        assert ctx.current_attempt is not None
        assert ctx.current_attempt.attempt_type == AttemptType.REVIEW
        assert ctx.current_attempt.workspace_record.basis_attempt_id == prior_attempt_id
    
    def test_task_routes_to_repair_on_failure(self):
        """Task routes to repair when validation fails."""
        executor = ClosedLoopExecutor()
        
        ctx = TaskContext(
            task_id="task-1",
            spec="Implement X",
            criteria=["criterion1"],
        )
        
        # Start build
        ctx = executor._start_build(ctx)
        
        # Initialize tracking for failure handling
        from crucible.policy.circuit_breaker import CircuitBreaker
        from crucible.runner.non_identical_rule import NonIdenticalRetryRule
        ctx.circuit_breaker = CircuitBreaker(executor.circuit_config)
        ctx.non_identical_rule = NonIdenticalRetryRule()
        
        # Simulate validation failure
        ctx.current_attempt.state = AttemptState.VALIDATED_FAIL
        from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
        ctx.current_attempt.failure_evidence = FailureEvidencePacket(
            failure_class=FailureClass.VALIDATION_FAILURE,
            attempt_id=ctx.current_attempt.attempt_id,
            criterion="test",
        )
        
        ctx = executor._handle_validation_fail(ctx, ctx.current_attempt)
        
        # Should route to repairing
        assert ctx.status == TaskStatus.REPAIRING
    
    def test_task_blocks_when_budget_exhausted(self):
        """Task blocks when budget exhausted."""
        # Use policy with 0 repair budget
        policy = BudgetPolicy(repair_attempt_budget=0)
        executor = ClosedLoopExecutor(budget_policy=policy)
        
        ctx = TaskContext(
            task_id="task-1",
            spec="Implement X",
            criteria=["criterion1"],
        )
        
        # Initialize tracker
        ctx = executor._start_build(ctx)
        
        # Manually exhaust repair budget
        ctx.budget_tracker._budgets["repair_attempt_budget"].total = 0
        ctx.budget_tracker._budgets["repair_attempt_budget"].spent = 1
        ctx.budget_tracker._budgets["repair_attempt_budget"].exhausted = True
        
        result = executor._start_repair(ctx)
        
        assert result.status == TaskStatus.BLOCKED
    
    def test_attempt_record_creation(self):
        """AttemptRecord creates correctly."""
        record = AttemptRecord(
            attempt_id="attempt-1",
            attempt_type=AttemptType.BUILD,
            state=AttemptState.RUNNING,
            workspace_record=WorkspaceRecord(lineage_type=WorkspaceLineageType.FRESH),
        )
        
        assert record.attempt_id == "attempt-1"
        assert record.attempt_type == AttemptType.BUILD
        assert record.state == AttemptState.RUNNING
    
    def test_determine_workspace_fresh_first_attempt(self):
        """First attempt gets fresh workspace."""
        executor = ClosedLoopExecutor()
        
        ctx = TaskContext(
            task_id="task-1",
            spec="test",
            criteria=[],
        )
        
        workspace = executor._determine_workspace(ctx)
        
        assert workspace.lineage_type == WorkspaceLineageType.FRESH
    
    def test_review_budget_exhaustion_blocks_review_start(self):
        """Review gate respects dedicated review budget."""
        policy = BudgetPolicy(review_rejection_budget=0)
        executor = ClosedLoopExecutor(budget_policy=policy)

        ctx = TaskContext(task_id="task-1", spec="Implement X", criteria=["criterion1"], review_required=True)
        from crucible.policy.budget_tracker import BudgetTracker
        from crucible.policy.circuit_breaker import CircuitBreaker
        from crucible.runner.non_identical_rule import NonIdenticalRetryRule
        ctx.budget_tracker = BudgetTracker(executor.budget_policy)
        ctx.circuit_breaker = CircuitBreaker(executor.circuit_config)
        ctx.non_identical_rule = NonIdenticalRetryRule()
        ctx = executor._start_build(ctx)
        ctx.current_attempt.state = AttemptState.VALIDATED_PASS
        ctx = executor._handle_validation_pass(ctx, ctx.current_attempt)

        assert ctx.status == TaskStatus.BLOCKED

    def test_validated_pass_completes_without_review_gate(self):
        """Validated implementation pass can close directly when review is not required."""
        executor = ClosedLoopExecutor()
        ctx = TaskContext(task_id="task-1", spec="Implement X", criteria=["criterion1"], review_required=False)
        ctx = executor.initialize_task(ctx)
        ctx = executor._start_build(ctx)
        ctx.current_attempt.state = AttemptState.VALIDATED_PASS

        ctx = executor._handle_validation_pass(ctx, ctx.current_attempt)

        assert ctx.status == TaskStatus.COMPLETE
        assert len(ctx.attempts) == 1

    def test_is_terminal_detects_complete(self):
        """_is_terminal returns True for COMPLETE."""
        executor = ClosedLoopExecutor()
        
        ctx = TaskContext(task_id="t1", spec="s", criteria=[])
        ctx.status = TaskStatus.COMPLETE
        
        assert executor._is_terminal(ctx) is True
    
    def test_is_terminal_detects_blocked(self):
        """_is_terminal returns True for BLOCKED."""
        executor = ClosedLoopExecutor()
        
        ctx = TaskContext(task_id="t1", spec="s", criteria=[])
        ctx.status = TaskStatus.BLOCKED
        
        assert executor._is_terminal(ctx) is True
    
    def test_is_terminal_detects_awaiting_user(self):
        """_is_terminal returns True for AWAITING_USER."""
        executor = ClosedLoopExecutor()
        
        ctx = TaskContext(task_id="t1", spec="s", criteria=[])
        ctx.status = TaskStatus.AWAITING_USER
        
        assert executor._is_terminal(ctx) is True
    
    def test_is_terminal_false_for_active(self):
        """_is_terminal returns False for active states."""
        executor = ClosedLoopExecutor()
        
        for status in [TaskStatus.BUILDING, TaskStatus.REPAIRING, TaskStatus.DEBUGGING]:
            ctx = TaskContext(task_id="t1", spec="s", criteria=[])
            ctx.status = status
            assert executor._is_terminal(ctx) is False
    
    def test_task_routes_to_debug_on_loop_detected(self):
        """Task routes to debug when loop detected."""
        executor = ClosedLoopExecutor()
        
        ctx = TaskContext(
            task_id="task-1",
            spec="Implement X",
            criteria=["criterion1"],
        )
        
        # Initialize tracking
        from crucible.policy.circuit_breaker import CircuitBreaker
        from crucible.runner.non_identical_rule import NonIdenticalRetryRule
        ctx.budget_tracker = executor._start_build(ctx).budget_tracker
        ctx.non_identical_rule = NonIdenticalRetryRule()
        ctx.circuit_breaker = CircuitBreaker(executor.circuit_config)
        
        # Start build
        ctx = executor._start_build(ctx)
        
        # Simulate loop detected failure
        from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
        ctx.current_attempt.state = AttemptState.VALIDATED_FAIL
        ctx.current_attempt.failure_evidence = FailureEvidencePacket(
            failure_class=FailureClass.LOOP_DETECTED,
            attempt_id=ctx.current_attempt.attempt_id,
        )
        
        ctx = executor._handle_validation_fail(ctx, ctx.current_attempt)
        
        # Should route to debugging
        assert ctx.status == TaskStatus.DEBUGGING