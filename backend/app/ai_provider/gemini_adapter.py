"""
GitReview AI — Gemini Adapter

Concrete implementation of AIProviderInterface for Google Gemini 2.5 Flash.
Thin HTTP layer: no prompt construction, no validation, no business logic.

LLD Part B.5: GeminiAdapter implements AIProviderInterface only.
HLD Section 5: retry-with-backoff on transient errors.
"""

from __future__ import annotations

import json
import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.ai_provider.interface import AIProviderInterface
from app.core.config import get_settings
from app.core.exceptions import AIProviderError, AIRateLimitError, AITimeoutError

logger = logging.getLogger(__name__)

_GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
)


class GeminiAdapter:
    """
    Concrete AIProviderInterface adapter for Gemini 2.5 Flash.
    Loaded once at application startup and injected via DI.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._model = self._settings.gemini_model
        self._api_key = self._settings.gemini_api_key
        self._timeout = self._settings.gemini_timeout_seconds

    async def generate(self, prompt: str) -> str:
        """
        Submit the prompt to Gemini and return the raw text response.
        Retries twice on transient errors with exponential backoff.
        """
        return await self._call_with_retry(prompt)

    @retry(
        retry=retry_if_exception_type(AIProviderError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _call_with_retry(self, prompt: str) -> str:
        url = _GEMINI_ENDPOINT.format(model=self._model, key=self._api_key)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,  # Low temperature for structured, reproducible output
                "maxOutputTokens": 4096,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            logger.warning("Gemini request timed out after %ss", self._timeout)
            raise AITimeoutError(f"Gemini API timed out after {self._timeout}s.") from exc
        except httpx.RequestError as exc:
            raise AIProviderError(f"Gemini network error: {exc}") from exc

        if response.status_code == 429:
            raise AIRateLimitError("Gemini API rate limit exceeded.")

        if not response.is_success:
            logger.error("Gemini API error %s: %s", response.status_code, response.text[:500])
            raise AIProviderError(
                f"Gemini returned HTTP {response.status_code}.",
                detail=response.text[:500],
            )

        try:
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AIProviderError("Unexpected Gemini response structure.") from exc


# Verify the adapter satisfies the Protocol at import time
assert isinstance(GeminiAdapter(), AIProviderInterface)
