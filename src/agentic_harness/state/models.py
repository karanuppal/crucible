"""Phase 1: Core state contracts for Agentic Harness v5.2.

All six state types from the technical design:
- ProjectState
- BuildState
- TaskState
- RunState
- ValidationState
- IntegrationState

Design rules:
- All fields required per spec (no Optional unless semantically nullable)
- JSON-serializable via dataclasses + custom encoder/decoder
- Schema validation rejects missing required fields, wrong types, unknown critical keys
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# --- Enums ---

class ProjectMode(str, Enum):
    EXISTING = "existing"
    GREENFIELD = "greenfield"


class TaskSize(str, Enum):
    S = "S"
    M = "M"
    L = "L"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    PARTIAL = "partial"
    KILLED = "killed"
    TIMED_OUT = "timed_out"


class RunRole(str, Enum):
    BUILDER = "builder"
    REVIEWER = "reviewer"
    DEBUGGER = "debugger"
    RESEARCHER = "researcher"
    INTEGRATOR = "integrator"
    SALVAGE = "salvage"


class ValidationVerdict(str, Enum):
    PASS = "pass"
    PASS_WITH_OBSERVATIONS = "pass_with_observations"
    FAIL = "fail"


class IntegrationStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


class CleanupStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"


# --- State Contracts ---

@dataclass
class ProjectState:
    projectId: str
    mode: ProjectMode
    repoPath: str
    remoteRepo: str
    activeBuildId: str
    machineProfileRef: str
    ledgerRef: str
    currentSpecRef: str


@dataclass
class BuildState:
    buildId: str
    projectId: str
    phase: str
    specRef: str
    taskIds: list[str] = field(default_factory=list)
    activeRunIds: list[str] = field(default_factory=list)
    integrationStateRef: str = ""
    validationStateRef: str = ""
    failureSummary: str = ""


@dataclass
class VerificationTriple:
    whatToBuild: str
    howToVerify: str
    whatFailureLooksLike: str


@dataclass
class TaskState:
    taskId: str
    title: str
    description: str
    roleNeeded: RunRole
    size: TaskSize
    dependencies: list[str] = field(default_factory=list)
    allowedPaths: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    verificationTriple: VerificationTriple | None = None
    status: TaskStatus = TaskStatus.PENDING
    assignedRunIds: list[str] = field(default_factory=list)
    rejections: list[dict[str, Any]] = field(default_factory=list)
    failureClass: str = ""


@dataclass
class RunState:
    runId: str
    projectId: str
    buildId: str
    taskId: str
    parentRunId: str
    role: RunRole
    backend: str
    model: str
    cwd: str
    worktreeRef: str
    status: RunStatus = RunStatus.PENDING
    blockingChildren: list[str] = field(default_factory=list)
    detachedChildren: list[str] = field(default_factory=list)
    retryGroupId: str = ""
    startedAt: str = ""
    lastProgressAt: str = ""
    artifactRefs: list[str] = field(default_factory=list)
    summary: str = ""
    cleanupStatus: CleanupStatus = CleanupStatus.PENDING


@dataclass
class CriterionResult:
    criterionId: str
    passed: bool
    evidence: str
    artifactRef: str = ""


@dataclass
class GateResult:
    gateName: str
    passed: bool
    mustPass: bool
    detail: str = ""


@dataclass
class ValidationState:
    validationId: str
    taskId: str
    criterionResults: list[CriterionResult] = field(default_factory=list)
    gateResults: list[GateResult] = field(default_factory=list)
    artifactRefs: list[str] = field(default_factory=list)
    verdict: ValidationVerdict = ValidationVerdict.FAIL


@dataclass
class IntegrationState:
    integrationId: str
    inputTaskIds: list[str] = field(default_factory=list)
    inputRunIds: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    mergeOrder: list[str] = field(default_factory=list)
    finalArtifacts: list[str] = field(default_factory=list)
    status: IntegrationStatus = IntegrationStatus.PENDING


# --- Serialization ---

class StateEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Enum):
            return o.value
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        return super().default(o)


def serialize(state: Any) -> str:
    """Serialize a state dataclass to JSON string."""
    return json.dumps(state, cls=StateEncoder, indent=2)


def _reconstruct(cls: type, data: dict[str, Any]) -> Any:
    """Reconstruct a dataclass from a dict, handling nested types."""
    import inspect
    hints = {k: v for k, v in cls.__dataclass_fields__.items()}
    kwargs = {}
    for field_name, field_obj in hints.items():
        if field_name not in data:
            if field_obj.default is not field_obj.default_factory:
                continue  # has default
            if field_obj.default_factory is not dataclass:
                continue
            raise ValueError(f"Missing required field: {field_name}")
        val = data[field_name]
        ft = cls.__dataclass_fields__[field_name].type
        # Handle enum fields
        if isinstance(ft, str):
            # resolve string annotations
            ft_resolved = _resolve_type(ft, cls)
        else:
            ft_resolved = ft
        if ft_resolved and isinstance(ft_resolved, type) and issubclass(ft_resolved, Enum):
            val = ft_resolved(val)
        elif ft_resolved and hasattr(ft_resolved, "__dataclass_fields__") and isinstance(val, dict):
            val = _reconstruct(ft_resolved, val)
        kwargs[field_name] = val
    return cls(**kwargs)


def _resolve_type(type_str: str, context_cls: type) -> type | None:
    """Resolve string type annotations to actual types."""
    import sys
    module = sys.modules[context_cls.__module__]
    # Handle Optional / union types
    clean = type_str.replace(" ", "")
    if clean.endswith("|None") or clean.startswith("None|"):
        clean = clean.replace("|None", "").replace("None|", "")
    # strip list[] wrapper
    if clean.startswith("list["):
        return None  # don't recurse into list element types for now
    return getattr(module, clean, None)


# --- Deserialization with validation ---

_STATE_TYPES: dict[str, type] = {
    "ProjectState": ProjectState,
    "BuildState": BuildState,
    "TaskState": TaskState,
    "RunState": RunState,
    "ValidationState": ValidationState,
    "IntegrationState": IntegrationState,
}

# Required fields per state type (fields with no default and no default_factory)
def _required_fields(cls: type) -> set[str]:
    result = set()
    for name, f in cls.__dataclass_fields__.items():
        from dataclasses import MISSING
        if f.default is MISSING and f.default_factory is MISSING:
            result.add(name)
    return result


def deserialize(type_name: str, json_str: str, *, strict: bool = True) -> Any:
    """Deserialize JSON string to a state dataclass.
    
    Args:
        type_name: one of the 6 state type names
        json_str: JSON string
        strict: if True, reject unknown keys
    
    Raises:
        ValueError: on missing required fields, unknown type, or unknown keys (strict mode)
        json.JSONDecodeError: on malformed JSON
    """
    if type_name not in _STATE_TYPES:
        raise ValueError(f"Unknown state type: {type_name}")
    
    cls = _STATE_TYPES[type_name]
    data = json.loads(json_str)
    
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")
    
    # Check required fields
    required = _required_fields(cls)
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Missing required fields: {sorted(missing)}")
    
    # Strict: reject unknown keys
    if strict:
        known = set(cls.__dataclass_fields__.keys())
        unknown = set(data.keys()) - known
        if unknown:
            raise ValueError(f"Unknown fields: {sorted(unknown)}")
    
    # Validate field types
    for field_name, val in data.items():
        if field_name not in cls.__dataclass_fields__:
            continue
        ft_str = cls.__dataclass_fields__[field_name].type
        if isinstance(ft_str, str):
            ft_resolved = _resolve_type(ft_str, cls)
        else:
            ft_resolved = ft_str
        
        # Enum validation
        if ft_resolved and isinstance(ft_resolved, type) and issubclass(ft_resolved, Enum):
            try:
                ft_resolved(val)
            except ValueError:
                valid = [e.value for e in ft_resolved]
                raise ValueError(f"Invalid value for {field_name}: {val!r}. Valid: {valid}")
        
        # List type validation
        if isinstance(ft_str, str) and ft_str.startswith("list[") and not isinstance(val, list):
            raise ValueError(f"Field {field_name} must be a list, got {type(val).__name__}")
        
        # Bool validation for fields that should be bool
        if isinstance(ft_str, str) and ft_str == "bool" and not isinstance(val, bool):
            raise ValueError(f"Field {field_name} must be a bool, got {type(val).__name__}")
    
    # Validate nested dataclass lists
    _validate_nested_lists(cls, data)
    
    return _reconstruct(cls, data)


def _validate_nested_lists(cls: type, data: dict[str, Any]) -> None:
    """Validate that list fields containing dataclasses have valid element schemas."""
    _NESTED_LIST_SCHEMAS: dict[str, dict[str, type]] = {
        "ValidationState": {
            "criterionResults": CriterionResult,
            "gateResults": GateResult,
        },
    }
    
    schema_map = _NESTED_LIST_SCHEMAS.get(cls.__name__, {})
    for field_name, element_cls in schema_map.items():
        if field_name not in data:
            continue
        items = data[field_name]
        if not isinstance(items, list):
            continue
        required = _required_fields(element_cls)
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"{field_name}[{i}] must be a dict, got {type(item).__name__}")
            missing = required - set(item.keys())
            if missing:
                raise ValueError(f"{field_name}[{i}] missing required fields: {sorted(missing)}")
            # Validate bool fields in nested objects
            for nested_field, nested_f in element_cls.__dataclass_fields__.items():
                if nested_field in item:
                    ft = nested_f.type
                    if ft == "bool" or ft is bool:
                        if not isinstance(item[nested_field], bool):
                            raise ValueError(
                                f"{field_name}[{i}].{nested_field} must be bool, got {type(item[nested_field]).__name__}"
                            )
