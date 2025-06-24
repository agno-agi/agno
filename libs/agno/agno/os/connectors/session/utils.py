"""Utility functions for the session manager"""

from typing import Any, Dict


def get_first_user_message(session: Dict[str, Any]) -> str:
    """Return the first user message in the given session"""
    if session.get("runs") is not None and len(session["runs"]) > 0:
        messages = session["runs"][0].get("messages", [])
        return messages[1].get("content", "") if len(messages) > 1 else ""
    return ""
