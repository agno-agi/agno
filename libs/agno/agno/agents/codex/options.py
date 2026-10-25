"""Typed options for the Codex thread and turn APIs.

These dictionaries use native SDK parameter names. CodexAgent's named settings
win over matching entries; None leaves the SDK default in place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from typing_extensions import TypedDict

if TYPE_CHECKING:
    from openai_codex.types import Personality, ReasoningSummary, ThreadSource, ThreadStartSource


class ThreadOptions(TypedDict, total=False):
    """Options accepted by Codex thread_start and/or thread_resume."""

    approval_mode: str
    base_instructions: str
    config: Dict[str, Any]
    cwd: str
    developer_instructions: str
    ephemeral: bool
    include_turns: bool
    model: str
    model_provider: str
    personality: Personality
    sandbox: str
    service_name: str
    service_tier: str
    session_start_source: ThreadStartSource
    thread_source: ThreadSource


class TurnOptions(TypedDict, total=False):
    """Options accepted by Codex turns; effort maps to reasoning_effort."""

    approval_mode: str
    cwd: str
    effort: str
    model: str
    output_schema: Dict[str, Any]
    personality: Personality
    sandbox: str
    service_tier: str
    source: str
    summary: ReasoningSummary
    turn_service_tier: str
