"""Existing-repo environment detection and provisioning."""

from .existing_repo import (
    ExistingRepoEnvironment,
    ExistingRepoProvisionError,
    ExistingRepoProvisionResult,
    ExistingRepoStrategy,
    choose_environment_strategy,
    detect_existing_repo_environment,
    ensure_existing_repo_environment,
)

__all__ = [
    "ExistingRepoEnvironment",
    "ExistingRepoProvisionError",
    "ExistingRepoProvisionResult",
    "ExistingRepoStrategy",
    "choose_environment_strategy",
    "detect_existing_repo_environment",
    "ensure_existing_repo_environment",
]
