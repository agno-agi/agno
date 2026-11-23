"""Utility functions for the DSPy adapter."""

from typing import Any, Dict, List, Optional


def build_input_with_history(input: Any, history: Optional[List[Dict[str, Any]]] = None) -> str:
    """Prepend conversation history to the input for multi-turn context.

    Formats prior messages as a labeled conversation transcript that DSPy
    can use as context for the current question.
    """
    if not history:
        return str(input)

    parts: List[str] = []
    for msg in history:
        if msg["role"] == "user":
            parts.append(f"User: {msg['content']}")
        elif msg["role"] == "tool":
            parts.append(f"Tool Result: {msg['content']}")
        else:
            parts.append(f"Assistant: {msg['content']}")
    parts.append(f"User: {input}")
    return "\n\n".join(parts)
