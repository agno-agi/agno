from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from agno.models.base import Model


@dataclass
class FollowupConfig:
    """Configuration for follow-up suggestion generation.

    Houses all parameters that control how follow-up suggestions are produced,
    keeping the Agent and Team class signatures lean.

    Attributes:
        model: Optional model to use for generating follow-ups.
               Falls back to the agent/team model when not set.
        instructions: Optional custom instructions appended to the default
                      system prompt to influence tone, style, or domain focus.
    """

    model: Optional[Model] = None
    instructions: Optional[str] = None
