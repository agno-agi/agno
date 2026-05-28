"""Shared helpers used by Context implementations."""

from __future__ import annotations

from typing import Any

from agno.context.provider import Answer


def answer_from_run(output: Any) -> Answer:
    """Turn an Agno RunOutput into an Answer."""
    text = output.get_content_as_string() if hasattr(output, "get_content_as_string") else str(output.content)
    return Answer(text=text or None)
