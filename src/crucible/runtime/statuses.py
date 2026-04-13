from __future__ import annotations

from enum import StrEnum


class AttemptTerminalStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    KILLED = "killed"
    TIMED_OUT = "timed_out"
    PARTIAL = "partial"


class TaskTerminalStatus(StrEnum):
    SUCCEEDED = "task_succeeded"
    FAILED = "task_failed"
    BLOCKED = "task_blocked"
    ESCALATED = "task_escalated"
    CANCELLED = "task_cancelled"


class RunTerminalStatus(StrEnum):
    SUCCEEDED = "run_succeeded"
    FAILED = "run_failed"
    BLOCKED = "run_blocked"
    ESCALATED = "run_escalated"
    CANCELLED = "run_cancelled"


TERMINAL_RUN_STATUSES = {status.value for status in RunTerminalStatus}
SUCCESSFUL_RUN_STATUSES = {RunTerminalStatus.SUCCEEDED.value}
NONSUCCESS_RUN_STATUSES = TERMINAL_RUN_STATUSES - SUCCESSFUL_RUN_STATUSES


def legacy_run_status(status: str) -> str:
    return {
        RunTerminalStatus.SUCCEEDED.value: "complete",
        RunTerminalStatus.FAILED.value: "failed",
        RunTerminalStatus.BLOCKED.value: "blocked",
        RunTerminalStatus.ESCALATED.value: "blocked",
        RunTerminalStatus.CANCELLED.value: "cancelled",
    }.get(status, status)
