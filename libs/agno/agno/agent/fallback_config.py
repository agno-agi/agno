"""Fallback model configuration for Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Union

from agno.models.base import Model


@dataclass
class FallbackConfig:
    """Configuration for fallback model behavior.

    Groups all fallback-related settings into a single object instead of
    spreading them across the Agent class.

    Example::

        FallbackConfig(
            models=[Claude(id="claude-sonnet-4-20250514")],
            rate_limit_models=[OpenAIChat(id="gpt-4o-mini")],
            context_window_models=[Claude(id="claude-sonnet-4-20250514")],
        )
    """

    # General fallback models tried when the primary model fails
    models: List[Union[Model, str]] = field(default_factory=list)
    # Fallback models tried specifically on rate-limit (429) errors
    rate_limit_models: List[Union[Model, str]] = field(default_factory=list)
    # Fallback models tried specifically on context-window-exceeded errors
    context_window_models: List[Union[Model, str]] = field(default_factory=list)

    @property
    def has_fallbacks(self) -> bool:
        return bool(self.models or self.rate_limit_models or self.context_window_models)
