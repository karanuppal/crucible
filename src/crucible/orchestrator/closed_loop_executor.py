"""
Closed-loop executor for Crucible v5.4.

Implements spec Section 6: deterministic task lifecycle loop until terminal state.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from crucible.failures.evidence_packet import FailureClass, FailureEvidencePacket
from crucible.failures.next_action_selector import NextActionSelector
from crucible.policy.budgets import BudgetPolicy
from crucible.policy.budget_tracker import BudgetTracker
from crucible.policy.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from crucible.runner.handoff_controller import HandoffController, HandoffDecision, Role
from crucible.runner.non_identical_rule import AttemptSignature, NonIdenticalRetryRule
from crucible.runner.role_executor import RoleExecutor, RoleExecutorConfig
from crucible.state.attempt_state import AttemptState
from crucible.state.attempt_type import AttemptType
from crucible.state.workspace_record import WorkspaceLineageType, WorkspaceRecord


class TaskStatus(str, Enum):
    """High-level task status for runtime."""
    
    QUEUED = "queued"
    BUILDING = "building"
    REPAIRING = "repairing"
    DEBUGGING = "debugging"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_USER = "awaiting_user"
    SALVAGING = "salvaging"
    INTEGRATING = "integrating"
    BLOCKED = "blocked"
    COMPLETE = "complete"


@dataclass
class AttemptRecord:
    """Record of a single attempt."""
    
    attempt_id: str
    attempt_type: AttemptType
    state: AttemptState
    workspace_record: WorkspaceRecord
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    failure_evidence: Optional[FailureEvidencePacket] = None
    review_result: Optional[dict] = None
    output: Optional[dict] = None
    budget_key_used: Optional[str] = None


@dataclass
class TaskContext:
    """Context for a task being executed."""
    
    task_id: str
    spec: str
    criteria: list[str]
    status: TaskStatus = TaskStatus.QUEUED
    review_required: bool = False
    attempts: list[AttemptRecord] = field(default_factory=list)
    current_attempt: Optional[AttemptRecord] = None
    budget_tracker: Optional[BudgetTracker] = None
    circuit_breaker: Optional[CircuitBreaker] = None
    non_identical_rule: Optional[NonIdenticalRetryRule] = None
    
    def get_previous_attempt(self) -> Optional[AttemptRecord]:
        """Get the most recent completed attempt."""
        completed = [a for a in self.attempts if a.state != AttemptState.PENDING]
        return completed[-1] if completed else None


class ClosedLoopExecutor:
    """
    Deterministic closed-loop task executor.
    
    Owns the full task lifecycle: build → validate → fail → repair → retest → ...
    until terminal state (complete, blocked, or awaiting_user).
    """
    
    def __init__(
        self,
        budget_policy: Optional[BudgetPolicy] = None,
        circuit_config: Optional[CircuitBreakerConfig] = None,
        role_config: Optional[RoleExecutorConfig] = None,
    ):
        """Initialize executor with policies."""
        self.budget_policy = budget_policy or BudgetPolicy()
        self.circuit_config = circuit_config or CircuitBreakerConfig()
        self.role_config = role_config or RoleExecutorConfig()
        self.role_executor = RoleExecutor(self.role_config)
    
    def initialize_task(self, task_context: TaskContext) -> TaskContext:
        """Ensure task policy trackers are present before the loop starts."""
        if task_context.budget_tracker is None:
            task_context.budget_tracker = BudgetTracker(self.budget_policy)
        if task_context.circuit_breaker is None:
            task_context.circuit_breaker = CircuitBreaker(self.circuit_config)
        if task_context.non_identical_rule is None:
            task_context.non_identical_rule = NonIdenticalRetryRule()
        return task_context

    def execute_task(
        self,
        task_context: TaskContext,
        *,
        attempt_runner: Callable[[TaskContext, AttemptRecord], TaskContext] | None = None,
    ) -> TaskContext:
        """
        Execute a task through the closed loop until terminal state.

        If ``attempt_runner`` is provided, this executor owns the full control loop
        and invokes the runner each time a concrete attempt enters RUNNING.
        """
        task_context = self.initialize_task(task_context)

        while not self._is_terminal(task_context):
            task_context = self._execute_next_step(task_context)
            if attempt_runner is None:
                continue
            attempt = task_context.current_attempt
            if attempt is None or attempt.state != AttemptState.RUNNING:
                continue
            task_context = attempt_runner(task_context, attempt)

        return task_context
    
    def _is_terminal(self, ctx: TaskContext) -> bool:
        """Check if task has reached terminal state."""
        return ctx.status in (
            TaskStatus.COMPLETE,
            TaskStatus.BLOCKED,
            TaskStatus.AWAITING_USER,
        )
    
    def _execute_next_step(self, ctx: TaskContext) -> TaskContext:
        """Execute the next step in the task lifecycle."""
        # Check circuit breaker
        if not ctx.circuit_breaker.can_continue():
            ctx.status = TaskStatus.BLOCKED
            return ctx
        
        # Determine next action based on current state
        if ctx.status == TaskStatus.QUEUED:
            return self._start_build(ctx)
        
        # Get current attempt to determine next step
        current = ctx.current_attempt
        if current is None:
            return self._start_build(ctx)
        
        # Handle based on current attempt state
        if current.state == AttemptState.RUNNING:
            # Should not happen in sync execution
            return ctx
        
        if current.state == AttemptState.VALIDATED_PASS:
            return self._handle_validation_pass(ctx, current)
        
        if current.state == AttemptState.VALIDATED_FAIL:
            return self._handle_validation_fail(ctx, current)
        
        if current.state == AttemptState.PARTIAL:
            return self._handle_partial(ctx, current)
        
        # Default: start new build
        return self._start_build(ctx)
    
    def _start_build(self, ctx: TaskContext) -> TaskContext:
        """Start a new build attempt."""
        # Initialize tracker if needed
        if ctx.budget_tracker is None:
            ctx.budget_tracker = BudgetTracker(self.budget_policy)
        if ctx.non_identical_rule is None:
            ctx.non_identical_rule = NonIdenticalRetryRule()
        
        # Check budget
        if not ctx.budget_tracker.can_attempt(AttemptType.BUILD):
            ctx.status = TaskStatus.BLOCKED
            return ctx
        
        # Consume budget
        ctx.budget_tracker.consume(AttemptType.BUILD, "build attempt")
        
        # Determine workspace lineage
        workspace_record = self._determine_workspace(ctx)
        
        # Create attempt record
        attempt = AttemptRecord(
            attempt_id=f"{ctx.task_id}-attempt-{len(ctx.attempts) + 1}",
            attempt_type=AttemptType.BUILD,
            state=AttemptState.RUNNING,
            workspace_record=workspace_record,
        )
        
        ctx.attempts.append(attempt)
        ctx.current_attempt = attempt
        ctx.status = TaskStatus.BUILDING
        
        return ctx
    
    def _determine_workspace(self, ctx: TaskContext) -> WorkspaceRecord:
        """Determine workspace lineage for next attempt."""
        prev = ctx.get_previous_attempt()
        
        if prev is None:
            # First attempt - fresh workspace
            return WorkspaceRecord(lineage_type=WorkspaceLineageType.FRESH)
        
        # Check if previous attempt can be used as basis
        if prev.state == AttemptState.VALIDATED_PASS and prev.attempt_type != AttemptType.REVIEW:
            return WorkspaceRecord(
                lineage_type=WorkspaceLineageType.REPAIR_BASIS,
                basis_attempt_id=prev.attempt_id,
            )

        if prev.state == AttemptState.VALIDATED_FAIL:
            # Use repair basis
            return WorkspaceRecord(
                lineage_type=WorkspaceLineageType.REPAIR_BASIS,
                basis_attempt_id=prev.attempt_id,
            )

        if prev.state == AttemptState.PARTIAL:
            # Use salvage inherit
            return WorkspaceRecord(
                lineage_type=WorkspaceLineageType.SALVAGE_INHERIT,
                basis_attempt_id=prev.attempt_id,
            )
        
        # Default to fresh
        return WorkspaceRecord(lineage_type=WorkspaceLineageType.FRESH)
    
    def _handle_validation_pass(
        self,
        ctx: TaskContext,
        attempt: AttemptRecord,
    ) -> TaskContext:
        """Handle validated pass - route to review or complete."""
        # Update attempt state
        attempt.state = AttemptState.VALIDATED_PASS
        
        # Record progress in circuit breaker
        ctx.circuit_breaker.record_progress()
        
        # Determine next handoff
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_PASS,
            attempt_type=attempt.attempt_type,
        )
        
        if decision.to_role == Role.REVIEWER and ctx.review_required:
            ctx.status = TaskStatus.AWAITING_REVIEW
            return self._start_review(ctx)

        ctx.status = TaskStatus.COMPLETE
        return ctx
    
    def _handle_validation_fail(
        self,
        ctx: TaskContext,
        attempt: AttemptRecord,
    ) -> TaskContext:
        """Handle validation failure - determine next action."""
        # Update attempt state
        attempt.state = AttemptState.VALIDATED_FAIL
        
        # Record failure in circuit breaker
        failure_class = attempt.failure_evidence.failure_class if attempt.failure_evidence else None
        if failure_class:
            ctx.circuit_breaker.record_failure(failure_class.value)
        
        # Check non-identical rule
        sig = self._create_signature(attempt)
        if ctx.non_identical_rule.get_signature_count() > 0:
            allowed, reason = ctx.non_identical_rule.is_allowed(sig)
            if not allowed:
                ctx.status = TaskStatus.BLOCKED
                return ctx
        
        ctx.non_identical_rule.record_attempt(sig)
        
        # Determine next action via handoff controller
        decision = HandoffController.decide_handoff(
            current_state=AttemptState.VALIDATED_FAIL,
            attempt_type=attempt.attempt_type,
            failure_evidence=attempt.failure_evidence,
        )
        
        # Handle decision
        if decision.terminal:
            ctx.status = TaskStatus.BLOCKED
            return ctx

        if decision.requires_user_input:
            ctx.status = TaskStatus.AWAITING_USER
            return ctx
        
        # Route to next attempt type
        if decision.attempt_type == AttemptType.REPAIR:
            ctx.status = TaskStatus.REPAIRING
            return self._start_repair(ctx)
        elif decision.attempt_type == AttemptType.DEBUG:
            ctx.status = TaskStatus.DEBUGGING
            return self._start_debug(ctx)
        elif decision.attempt_type == AttemptType.SALVAGE:
            ctx.status = TaskStatus.SALVAGING
            return self._start_salvage(ctx)
        
        ctx.status = TaskStatus.BLOCKED
        return ctx
    
    def _handle_partial(
        self,
        ctx: TaskContext,
        attempt: AttemptRecord,
    ) -> TaskContext:
        """Handle partial output - route to salvage."""
        attempt.state = AttemptState.PARTIAL
        ctx.status = TaskStatus.SALVAGING
        return self._start_salvage(ctx)
    
    def _start_repair(self, ctx: TaskContext) -> TaskContext:
        """Start a repair attempt."""
        if not ctx.budget_tracker.can_attempt(AttemptType.REPAIR):
            ctx.status = TaskStatus.BLOCKED
            return ctx
        
        ctx.budget_tracker.consume(AttemptType.REPAIR, "repair attempt")
        
        workspace = self._determine_workspace(ctx)
        
        attempt = AttemptRecord(
            attempt_id=f"{ctx.task_id}-attempt-{len(ctx.attempts) + 1}",
            attempt_type=AttemptType.REPAIR,
            state=AttemptState.RUNNING,
            workspace_record=workspace,
            budget_key_used="repair_attempt_budget",
        )
        
        ctx.attempts.append(attempt)
        ctx.current_attempt = attempt
        ctx.status = TaskStatus.REPAIRING
        
        return ctx
    
    def _start_debug(self, ctx: TaskContext) -> TaskContext:
        """Start a debug attempt."""
        budget_key = self._debug_budget_key(ctx)
        if not ctx.budget_tracker.can_attempt_budget(budget_key):
            ctx.status = TaskStatus.BLOCKED
            return ctx
        
        ctx.budget_tracker.consume_budget(budget_key, "debug attempt")
        
        workspace = self._determine_workspace(ctx)
        
        attempt = AttemptRecord(
            attempt_id=f"{ctx.task_id}-attempt-{len(ctx.attempts) + 1}",
            attempt_type=AttemptType.DEBUG,
            state=AttemptState.RUNNING,
            workspace_record=workspace,
            budget_key_used=budget_key,
        )
        
        ctx.attempts.append(attempt)
        ctx.current_attempt = attempt
        ctx.status = TaskStatus.DEBUGGING
        
        return ctx
    
    def _debug_budget_key(self, ctx: TaskContext) -> str:
        """Use deep recovery budget when policy has escalated a repeated/stuck failure."""
        failure = ctx.current_attempt.failure_evidence if ctx.current_attempt else None
        if failure and (failure.failure_class == FailureClass.STUCK_OR_REPEATING or failure.repeated_failure):
            return "deep_recovery_budget"
        return "debug_attempt_budget"

    def _start_review(self, ctx: TaskContext) -> TaskContext:
        """Start a review attempt and consume review-rejection budget."""
        if not ctx.budget_tracker.can_attempt(AttemptType.REVIEW):
            ctx.status = TaskStatus.BLOCKED
            return ctx

        ctx.budget_tracker.consume(AttemptType.REVIEW, "review gate attempt")
        workspace = self._determine_workspace(ctx)

        attempt = AttemptRecord(
            attempt_id=f"{ctx.task_id}-attempt-{len(ctx.attempts) + 1}",
            attempt_type=AttemptType.REVIEW,
            state=AttemptState.RUNNING,
            workspace_record=workspace,
        )

        ctx.attempts.append(attempt)
        ctx.current_attempt = attempt
        ctx.status = TaskStatus.AWAITING_REVIEW

        return ctx

    def _start_salvage(self, ctx: TaskContext) -> TaskContext:
        """Start a salvage attempt."""
        if not ctx.budget_tracker.can_attempt(AttemptType.SALVAGE):
            ctx.status = TaskStatus.BLOCKED
            return ctx
        
        ctx.budget_tracker.consume(AttemptType.SALVAGE, "salvage attempt")
        
        workspace = WorkspaceRecord(
            lineage_type=WorkspaceLineageType.SALVAGE_INHERIT,
            basis_attempt_id=ctx.current_attempt.attempt_id if ctx.current_attempt else None,
        )
        
        attempt = AttemptRecord(
            attempt_id=f"{ctx.task_id}-attempt-{len(ctx.attempts) + 1}",
            attempt_type=AttemptType.SALVAGE,
            state=AttemptState.RUNNING,
            workspace_record=workspace,
        )
        
        ctx.attempts.append(attempt)
        ctx.current_attempt = attempt
        ctx.status = TaskStatus.SALVAGING
        
        return ctx
    
    def _create_signature(self, attempt: AttemptRecord) -> AttemptSignature:
        """Create attempt signature for non-identical rule."""
        failure_signature = ""
        if attempt.failure_evidence is not None and attempt.failure_evidence.signature is not None:
            failure_signature = attempt.failure_evidence.signature
        return AttemptSignature(
            prompt=f"{attempt.attempt_type.value}:{failure_signature}",
            role=attempt.attempt_type.value,
            workspace_basis=attempt.workspace_record.basis_attempt_id,
        )