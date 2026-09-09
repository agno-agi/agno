"""Helpers for evaluating team-member run outcomes (#5278).

When a member model returns None/empty content (seen with some Gemini versions),
Team delegation must surface a hard incomplete signal instead of silently finishing.
"""

from __future__ import annotations

from typing import Any, Optional


def member_run_is_empty(member_agent_run_response: Optional[Any]) -> bool:
    """Return True when a member run produced no usable content or tool results.

    Empty/None model responses are a known multi-agent failure mode: the team
    leader may stop after "I transferred the task..." without further work.
    """
    if member_agent_run_response is None:
        return True
    content = getattr(member_agent_run_response, "content", None)
    tools = getattr(member_agent_run_response, "tools", None)
    has_tools = tools is not None and len(tools) > 0
    if content is None:
        return not has_tools
    if isinstance(content, str) and not content.strip():
        return not has_tools
    return False


def empty_member_response_message(member_name: Optional[str] = None) -> str:
    """User/leader-visible message when a member returns nothing usable."""
    label = member_name or "member"
    return (
        f"No usable response from team member '{label}' "
        f"(empty or None content; possible model/provider early stop). "
        f"The delegated task was NOT completed. "
        f"Retry the delegation, disable member streaming if the team is streaming, "
        f"or switch models."
    )
