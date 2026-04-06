"""Phase 6 tests: Optional accelerators."""

import pytest

from agentic_harness.accelerators.adapters import (
    Backend, BackendCapabilities, BACKEND_CAPABILITIES,
    BackendRouter, create_default_router,
)


class TestBackendCapabilities:
    def test_all_backends_have_capabilities(self):
        for backend in Backend:
            assert backend in BACKEND_CAPABILITIES
            caps = BACKEND_CAPABILITIES[backend]
            assert isinstance(caps, BackendCapabilities)
    
    def test_codex_supports_streaming(self):
        caps = BACKEND_CAPABILITIES[Backend.CODEX]
        assert caps.supports_streaming
    
    def test_code_supports_limited(self):
        caps = BACKEND_CAPABILITIES[Backend.CODE]
        assert not caps.supports_streaming
        assert not caps.supports_multimodal


class TestBackendRouter:
    def test_route_to_available_backend(self):
        router = BackendRouter()
        router.register_adapter(Backend.CODE, lambda: None)
        
        result = router.route({})
        
        assert result == Backend.CODE
    
    def test_route_prefers_explicit(self):
        router = BackendRouter()
        router.register_adapter(Backend.CODEX, lambda: None)
        router.register_adapter(Backend.CODE, lambda: None)
        
        result = router.route({}, preferred=Backend.CODEX)
        
        assert result == Backend.CODEX
    
    def test_route_respects_requirements(self):
        router = BackendRouter()
        router.register_adapter(Backend.CODE, lambda: None)
        
        # CODE doesn't support streaming, so should fail
        result = router.route({"streaming": True})
        
        # Falls back to CODE as default when no match
        assert result == Backend.CODE
    
    def test_fallback_used_when_no_match(self):
        router = BackendRouter()
        router.register_adapter(Backend.CODE, lambda: None)
        router.set_fallback(Backend.CODE)
        
        result = router.route({"impossible_requirement": True})
        
        assert result == Backend.CODE
    
    def test_is_available(self):
        router = BackendRouter()
        router.register_adapter(Backend.CODEX, lambda: None)
        
        assert router.is_available(Backend.CODEX)
        assert not router.is_available(Backend.CLAUDE_CODE)
    
    def test_get_capabilities(self):
        router = BackendRouter()
        
        caps = router.get_capabilities(Backend.CODEX)
        
        assert caps is not None
        assert caps.supports_streaming


class TestCreateDefaultRouter:
    def test_creates_router_with_fallback(self):
        router = create_default_router()
        
        assert router._fallback == Backend.CODE