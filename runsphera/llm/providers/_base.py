"""Shared types for all LLM provider implementations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResult:
    """Provider-agnostic return shape from a `coach_message` call.

    `text`  — the model's final response, stripped of whitespace.
    `model` — the model identifier the provider actually used (echo of
              the requested name in most cases).
    `usage` — provider-shaped usage dict (input/output tokens, etc.);
              best-effort, may be empty if the provider doesn't expose it.
    """
    text: str
    model: str
    usage: dict[str, Any]
