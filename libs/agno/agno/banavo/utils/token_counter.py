from typing import Any, List

import tiktoken


def extract_text(content: Any) -> str:
    """Safely extract text from various message content formats."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    if isinstance(content, dict):
        return content.get("text", "") or str(content)
    return str(content)


def count_tokens(messages: List[Any], model_encoding: str = "cl100k_base") -> int:
    """Count total tokens in a list of messages using the specified tokenizer."""
    encoding = tiktoken.get_encoding(model_encoding)
    total_tokens = 0

    for msg in messages:
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        text = extract_text(content)
        total_tokens += len(encoding.encode(text))

    return total_tokens
