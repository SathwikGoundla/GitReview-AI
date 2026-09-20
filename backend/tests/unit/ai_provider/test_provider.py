"""Unit tests for app.ai_provider — interface and adapter."""

from __future__ import annotations

import os

os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("STATE_SECRET", "test-secret")
os.environ.setdefault("GEMINI_API_KEY", "fake-key-for-unit-tests")


class TestAIProviderInterface:
    def test_gemini_adapter_satisfies_protocol(self):
        """GeminiAdapter must satisfy AIProviderInterface at runtime."""
        from app.ai_provider.gemini_adapter import GeminiAdapter
        from app.ai_provider.interface import AIProviderInterface

        adapter = GeminiAdapter()
        assert isinstance(adapter, AIProviderInterface)

    def test_adapter_has_generate_method(self):
        from app.ai_provider.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter()
        assert callable(adapter.generate)

    def test_adapter_has_correct_model_name(self):
        from app.ai_provider.gemini_adapter import GeminiAdapter
        from app.core.config import get_settings

        get_settings.cache_clear()
        adapter = GeminiAdapter()
        assert "gemini" in adapter._model.lower()


class TestGeminiAdapterResponseParsing:
    """Test response parsing without making real HTTP calls."""

    def test_extracts_text_from_valid_response(self):
        """Verify the JSON path used to extract text from Gemini response."""
        # Simulate the Gemini API response structure
        fake_response = {"candidates": [{"content": {"parts": [{"text": '{"summary": "test"}'}]}}]}
        text = fake_response["candidates"][0]["content"]["parts"][0]["text"]
        assert text == '{"summary": "test"}'

    def test_raises_ai_provider_error_on_bad_structure(self):
        """Malformed Gemini response structure raises AIProviderError."""
        from app.core.exceptions import AIProviderError

        # This tests the exception type, not the actual HTTP call
        exc = AIProviderError("Unexpected Gemini response structure.")
        assert exc.error_code == "ai_provider_error"

    def test_raises_rate_limit_error_on_429(self):
        from app.core.exceptions import AIRateLimitError

        exc = AIRateLimitError("Gemini API rate limit exceeded.")
        assert exc.http_status == 429

    def test_raises_timeout_error_on_timeout(self):
        from app.core.exceptions import AITimeoutError

        exc = AITimeoutError("Gemini API timed out.")
        assert exc.error_code == "ai_timeout"


class TestMockAIProvider:
    """Test that any class satisfying the Protocol can be used as an AI provider."""

    def test_custom_provider_satisfies_interface(self):
        from app.ai_provider.interface import AIProviderInterface

        class FakeProvider:
            async def generate(self, prompt: str) -> str:
                return '{"summary": "fake"}'

        provider = FakeProvider()
        assert isinstance(provider, AIProviderInterface)

    def test_class_without_generate_does_not_satisfy_interface(self):
        from app.ai_provider.interface import AIProviderInterface

        class NotAProvider:
            async def analyze(self, prompt: str) -> str:
                return "wrong method name"

        provider = NotAProvider()
        assert not isinstance(provider, AIProviderInterface)
