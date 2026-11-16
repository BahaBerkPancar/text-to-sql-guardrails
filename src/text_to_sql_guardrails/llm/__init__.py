"""LLM adapters for producing untrusted SQL candidates."""

from .base import (
    Attempt,
    Generation,
    LlmFailed,
    LlmNotConfigured,
    LlmRefused,
    SqlGenerator,
)

__all__ = [
    "Attempt",
    "Generation",
    "LlmFailed",
    "LlmNotConfigured",
    "LlmRefused",
    "SqlGenerator",
]
