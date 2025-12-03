import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agno.media import File
from agno.models.message import Message
from agno.tools.function import Function


@lru_cache(maxsize=16)
def _get_tiktoken_encoding(model: str):
    """Get tiktoken encoding for a model. Returns None if unavailable."""
    try:
        import tiktoken

        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            # Unknown model - use cl100k_base as fallback
            return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        return None


def count_text_tokens_tiktoken(text: str, model: str = "gpt-4o") -> Optional[int]:
    """Count tokens in text using tiktoken.

    Args:
        text: The text to count tokens for.
        model: Model name to determine encoding (default: gpt-4o).

    Returns:
        Token count, or None if tiktoken is not available.
    """
    if not text:
        return 0

    enc = _get_tiktoken_encoding(model)
    if enc is None:
        return None

    return len(enc.encode(text, disallowed_special=()))


def count_message_tokens_tiktoken(message: Message, model: str = "gpt-4o") -> Optional[int]:
    """Count tokens in a Message using tiktoken for text, estimation for media.

    Args:
        message: The message to count tokens for.
        model: Model name to determine encoding.

    Returns:
        Token count, or None if tiktoken is not available.
    """
    enc = _get_tiktoken_encoding(model)
    if enc is None:
        return None

    tokens = 4
    content = message.compressed_content or message.content
    if content:
        if isinstance(content, str):
            tokens += len(enc.encode(content, disallowed_special=()))
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    tokens += len(enc.encode(item, disallowed_special=()))
                elif isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        tokens += len(enc.encode(str(text), disallowed_special=()))
                    else:
                        tokens += len(enc.encode(json.dumps(item), disallowed_special=()))
        else:
            tokens += len(enc.encode(str(content), disallowed_special=()))

    if message.tool_calls:
        tokens += len(enc.encode(json.dumps(message.tool_calls), disallowed_special=()))

    if message.tool_call_id:
        tokens += len(enc.encode(message.tool_call_id, disallowed_special=()))

    if message.reasoning_content:
        tokens += len(enc.encode(message.reasoning_content, disallowed_special=()))

    if message.redacted_reasoning_content:
        tokens += len(enc.encode(message.redacted_reasoning_content, disallowed_special=()))

    if message.name:
        tokens += len(enc.encode(message.name, disallowed_special=()))

    tokens += _count_media_tokens(message)

    return tokens


def count_messages_tokens_tiktoken(messages: List[Message], model: str = "gpt-4o") -> Optional[int]:
    """Count total tokens across messages using tiktoken.

    Args:
        messages: List of messages to count tokens for.
        model: Model name to determine encoding.

    Returns:
        Token count, or None if tiktoken is not available.
    """
    if not messages:
        return 0

    enc = _get_tiktoken_encoding(model)
    if enc is None:
        return None

    total = 0
    for msg in messages:
        msg_tokens = count_message_tokens_tiktoken(msg, model)
        if msg_tokens is None:
            return None
        total += msg_tokens

    return total + 3


def count_tool_tokens_tiktoken(tools: List[Union[Function, Dict[str, Any]]], model: str = "gpt-4o") -> Optional[int]:
    """Count tokens in tool definitions using tiktoken.

    Args:
        tools: List of tools/functions to count tokens for.
        model: Model name to determine encoding.

    Returns:
        Token count, or None if tiktoken is not available.
    """
    if not tools:
        return 0

    enc = _get_tiktoken_encoding(model)
    if enc is None:
        return None

    total = 0
    for tool in tools:
        tool_dict = tool.to_dict() if hasattr(tool, "to_dict") else tool
        total += len(enc.encode(json.dumps(tool_dict), disallowed_special=()))

    return total


def count_tokens_with_tiktoken(
    messages: List[Message],
    tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
    model: str = "gpt-4o",
) -> Optional[int]:
    """Count tokens for messages and tools using tiktoken.

    This is the main entry point for tiktoken-based counting.
    Falls back to None if tiktoken is not available.

    Args:
        messages: List of messages to count tokens for.
        tools: Optional list of tools to include in count.
        model: Model name to determine encoding.

    Returns:
        Token count, or None if tiktoken is not available.
    """
    msg_tokens = count_messages_tokens_tiktoken(messages, model)
    if msg_tokens is None:
        return None

    total = msg_tokens

    if tools:
        tool_tokens = count_tool_tokens_tiktoken(tools, model)
        if tool_tokens is None:
            return None
        total += tool_tokens

    return total


def count_tokens(text: str) -> int:
    """Estimate tokens in text (~4 chars per token)."""
    if not text:
        return 0
    return len(text) // 4


def count_image_tokens(width: int, height: int, detail: str = "auto") -> int:
    """Estimate tokens for an image."""
    if width <= 0 or height <= 0:
        return 0

    if detail == "low":
        return 85

    if max(width, height) > 2048:
        scale = 2048 / max(width, height)
        width, height = int(width * scale), int(height * scale)

    if min(width, height) > 768:
        scale = 768 / min(width, height)
        width, height = int(width * scale), int(height * scale)

    tiles = math.ceil(width / 512) * math.ceil(height / 512)
    return 85 + (170 * tiles)


def count_audio_tokens(duration_seconds: float) -> int:
    """Estimate tokens for audio."""
    if duration_seconds <= 0:
        return 0
    return int(duration_seconds * 25)


def count_video_tokens(
    duration_seconds: float,
    width: int = 512,
    height: int = 512,
    fps: float = 1.0,
) -> int:
    """Estimate tokens for video."""
    if duration_seconds <= 0:
        return 0
    num_frames = max(int(duration_seconds * fps), 1)
    return num_frames * count_image_tokens(width, height, "high")


def count_file_tokens(file: File) -> int:
    """Estimate tokens for a file from content, filepath, or URL."""
    content = getattr(file, "content", None)
    if content:
        if isinstance(content, str):
            return len(content) // 4
        elif isinstance(content, bytes):
            return len(content) // 4

    filepath = getattr(file, "filepath", None)
    if filepath:
        try:
            path = Path(filepath) if isinstance(filepath, str) else filepath
            if path.exists():
                return path.stat().st_size // 4
        except Exception:
            pass

    url = getattr(file, "url", None)
    if url:
        try:
            import urllib.request

            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    return int(content_length) // 4
        except Exception:
            pass

    return 0


def count_message_tokens(message: Message) -> int:
    """Count tokens in a Message."""
    tokens = 4
    content = message.compressed_content or message.content
    if content:
        if isinstance(content, str):
            tokens += count_tokens(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    tokens += count_tokens(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    tokens += count_tokens(str(text)) if text else count_tokens(json.dumps(item))
        else:
            tokens += count_tokens(str(content))

    if message.tool_calls:
        tokens += count_tokens(json.dumps(message.tool_calls))
    if message.tool_call_id:
        tokens += count_tokens(message.tool_call_id)
    if message.reasoning_content:
        tokens += count_tokens(message.reasoning_content)
    if message.redacted_reasoning_content:
        tokens += count_tokens(message.redacted_reasoning_content)
    if message.name:
        tokens += count_tokens(message.name)

    tokens += _count_media_tokens(message)

    return tokens


def _count_media_tokens(message: Message) -> int:
    tokens = 0

    if message.images:
        for img in message.images:
            tokens += count_image_tokens(
                getattr(img, "width", None) or 512,
                getattr(img, "height", None) or 512,
                getattr(img, "detail", None) or "auto",
            )

    if message.audio:
        for aud in message.audio:
            tokens += count_audio_tokens(getattr(aud, "duration", None) or 0)

    if message.videos:
        for vid in message.videos:
            tokens += count_video_tokens(
                getattr(vid, "duration", None) or 0,
                getattr(vid, "width", None) or 512,
                getattr(vid, "height", None) or 512,
                getattr(vid, "fps", None) or 1.0,
            )

    if message.files:
        for file in message.files:
            tokens += count_file_tokens(file)

    return tokens


def count_messages_tokens(messages: List[Message]) -> int:
    """Count total tokens across a list of messages."""
    if not messages:
        return 0
    total = sum(count_message_tokens(msg) for msg in messages)
    return total + 3


def count_tool_tokens(tools: List[Union[Function, Dict[str, Any]]]) -> int:
    """Count tokens in tool/function definitions."""
    if not tools:
        return 0
    total = 0
    for tool in tools:
        tool_dict = tool.to_dict() if hasattr(tool, "to_dict") else tool
        total += len(json.dumps(tool_dict)) // 6
    return total


def estimate_context_tokens(
    messages: List[Message],
    tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
) -> int:
    """Estimate total tokens for messages and tools."""
    total = count_messages_tokens(messages)
    if tools:
        total += count_tool_tokens(tools)
    return total


def log_token_comparison(estimated: int, actual: int) -> None:
    """Log estimated vs actual token counts.

    Args:
        estimated: Token count from model's count_tokens method.
        actual: Actual token count from provider response.
    """
    from agno.utils.log import log_debug

    log_debug(f"Tokens - estimated: {estimated}, actual: {actual}")
