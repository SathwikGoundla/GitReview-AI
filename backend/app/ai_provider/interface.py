"""
GitReview AI — AI Provider Interface

Protocol-based abstraction so the Gemini implementation is swappable.
The Orchestrator depends on AIProviderInterface, never on GeminiAdapter directly.

LLD Part B.5: AIProviderInterface defines the contract only — no implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AIProviderInterface(Protocol):
    """
    Contract every AI provider adapter must satisfy.
    generate() takes a fully-constructed prompt and returns the raw model response.
    Validation of that response is the Orchestrator's responsibility.
    """

    async def generate(self, prompt: str) -> str:
        """
        Submit a structured prompt and return the raw model response string.

        Raises:
            AIProviderError: on provider-side error
            AITimeoutError: on timeout
            AIRateLimitError: on rate-limit exhaustion
        """
        ...
