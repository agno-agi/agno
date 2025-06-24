"""Utility functions for the session manager"""

from agno.session import Session


def get_first_user_message(session: Session) -> str:
    """Return the first user message in the given session"""
    if session.runs is not None:
        messages = session.runs[0].get("messages", [])
        return messages[1].get("content") if len(messages) > 1 else ""
    return ""
