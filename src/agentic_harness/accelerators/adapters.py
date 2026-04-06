"""Phase 6: Optional backend accelerators.

From spec (§17):
- Backend capability routing
- Adapter implementations (Claude Code, Codex)
- Semantic parity across backends
- Fallback behavior when accelerator unavailable
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class Backend(str, Enum):
    """Available backends."""
    CODEX = "codex"
    CLAUDE_CODE = "claude_code"
    CODE = "code"  # Generic code execution
    SUBAGENT = "subagent"


@dataclass
class BackendCapabilities:
    """What a backend can do."""
    supports_streaming: bool
    supports_multimodal: bool
    max_context_tokens: int
    supports_function_calling: bool
    supports_json_mode: bool
    average_latency_ms: int


# Capability declarations per backend
BACKEND_CAPABILITIES: dict[Backend, BackendCapabilities] = {
    Backend.CODEX: BackendCapabilities(
        supports_streaming=True,
        supports_multimodal=True,
        max_context_tokens=200000,
        supports_function_calling=True,
        supports_json_mode=True,
        average_latency_ms=2000,
    ),
    Backend.CLAUDE_CODE: BackendCapabilities(
        supports_streaming=True,
        supports_multimodal=True,
        max_context_tokens=200000,
        supports_function_calling=True,
        supports_json_mode=True,
        average_latency_ms=1500,
    ),
    Backend.CODE: BackendCapabilities(
        supports_streaming=False,
        supports_multimodal=False,
        max_context_tokens=32000,
        supports_function_calling=False,
        supports_json_mode=False,
        average_latency_ms=500,
    ),
    Backend.SUBAGENT: BackendCapabilities(
        supports_streaming=True,
        supports_multimodal=False,
        max_context_tokens=100000,
        supports_function_calling=True,
        supports_json_mode=True,
        average_latency_ms=3000,
    ),
}


class BackendRouter:
    """Routes requests to appropriate backend based on requirements."""
    
    def __init__(self) -> None:
        self._adapters: dict[Backend, Callable] = {}
        self._fallback: Backend | None = None
    
    def register_adapter(self, backend: Backend, adapter: Callable) -> None:
        """Register a backend adapter."""
        self._adapters[backend] = adapter
    
    def set_fallback(self, backend: Backend) -> None:
        """Set fallback backend."""
        self._fallback = backend
    
    def route(
        self,
        requirements: dict[str, Any],
        preferred: Backend | None = None,
    ) -> Backend:
        """Route to best backend for requirements."""
        # If preferred is available and meets requirements, use it
        if preferred and preferred in self._adapters:
            if self._meets_requirements(preferred, requirements):
                return preferred
        
        # Find first backend that meets requirements
        for backend in Backend:
            if backend in self._adapters:
                if self._meets_requirements(backend, requirements):
                    return backend
        
        # Fallback
        if self._fallback and self._fallback in self._adapters:
            return self._fallback
        
        # Default to CODE if nothing else available
        return Backend.CODE
    
    def _meets_requirements(self, backend: Backend, requirements: dict) -> bool:
        """Check if backend meets requirements."""
        caps = BACKEND_CAPABILITIES.get(backend)
        if not caps:
            return False
        
        if requirements.get("streaming") and not caps.supports_streaming:
            return False
        if requirements.get("multimodal") and not caps.supports_multimodal:
            return False
        if requirements.get("max_tokens"):
            if caps.max_context_tokens < requirements["max_tokens"]:
                return False
        if requirements.get("function_calling") and not caps.supports_function_calling:
            return False
        if requirements.get("json_mode") and not caps.supports_json_mode:
            return False
        
        return True
    
    def get_capabilities(self, backend: Backend) -> BackendCapabilities | None:
        """Get capabilities for a backend."""
        return BACKEND_CAPABILITIES.get(backend)
    
    def is_available(self, backend: Backend) -> bool:
        """Check if backend is available (has adapter registered)."""
        return backend in self._adapters


def create_default_router() -> BackendRouter:
    """Create router with default configuration."""
    router = BackendRouter()
    router.set_fallback(Backend.CODE)
    return router