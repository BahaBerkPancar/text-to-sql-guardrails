"""Scripted offline SQL generator for tests and demos."""

from __future__ import annotations

from dataclasses import dataclass

from .base import Attempt, Generation


@dataclass(frozen=True)
class FakeCall:
    question: str
    schema_prompt: str
    previous: list[Attempt]


class FakeGenerator:
    def __init__(self, script: list[Generation]) -> None:
        self._script = list(script)
        self.calls: list[FakeCall] = []

    def generate(
        self,
        question: str,
        schema_prompt: str,
        previous: list[Attempt],
    ) -> Generation:
        self.calls.append(FakeCall(question, schema_prompt, list(previous)))
        if not self._script:
            raise AssertionError("FakeGenerator script is exhausted")
        return self._script.pop(0)
