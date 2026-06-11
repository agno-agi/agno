"""Text extraction helpers for AG-UI user messages and Agno response chunks."""

from typing import List

from ag_ui.core.types import Message as AGUIMessage

from agno.run.agent import RunContentEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.utils.message import get_text_from_message


def extract_agui_user_input(messages: List[AGUIMessage]) -> str:
    """Extract the last user message content from AG-UI messages.

    AG-UI frontends send the full conversation history on every request.
    The agent manages its own history via session DB, so we only need the
    latest user message as input — matching the REST API pattern.
    """
    for msg in reversed(messages):
        if msg.role == "user" and msg.content is not None:
            # UserMessage.content is Union[str, List[InputContent]]
            if isinstance(msg.content, str):
                return msg.content
            # Multimodal: extract text parts
            if isinstance(msg.content, list):
                text_parts = []
                for part in msg.content:
                    if hasattr(part, "type") and part.type == "text" and hasattr(part, "text"):
                        text_parts.append(part.text)
                if text_parts:
                    return "\n".join(text_parts)
    return ""


def extract_response_chunk_content(response: RunContentEvent) -> str:
    """Given a response stream chunk, find and extract the content."""

    if hasattr(response, "messages") and response.messages:  # type: ignore
        for msg in reversed(response.messages):  # type: ignore
            if hasattr(msg, "role") and msg.role == "assistant" and hasattr(msg, "content") and msg.content:
                # Handle structured outputs from messages
                return get_text_from_message(msg.content)

    # Handle structured outputs
    return get_text_from_message(response.content) if response.content is not None else ""


def extract_team_response_chunk_content(response: TeamRunContentEvent) -> str:
    """Given a team response stream chunk, find and extract the content.

    Recursively folds in member responses so the AG-UI client sees a single
    consolidated text instead of N separate member text deltas.
    """

    # Handle Team members' responses
    members_content = []
    if hasattr(response, "member_responses") and response.member_responses:  # type: ignore
        for member_resp in response.member_responses:  # type: ignore
            if isinstance(member_resp, RunContentEvent):
                member_content = extract_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
            elif isinstance(member_resp, TeamRunContentEvent):
                member_content = extract_team_response_chunk_content(member_resp)
                if member_content:
                    members_content.append(f"Team member: {member_content}")
    members_response = "\n".join(members_content) if members_content else ""

    # Handle structured outputs
    main_content = get_text_from_message(response.content) if response.content is not None else ""

    return main_content + members_response
