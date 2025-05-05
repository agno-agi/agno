from typing import Any, Dict

from agno.agent import Message
from agno.utils.log import log_warning
from agno.utils.openai import process_image

ROLE_MAP = {
    "user": "user",
    "assistant": "assistant",
    "system": "system",
    "tool": "tool",
}

TOOL_CALL_ROLE_MAP = {
    "user": "user",
    "assistant": "assistant",
    "system": "user",
    "tool": "tool",
}


def format_message(message: Message, openai_like: bool = False, tool_calls: bool = False) -> Dict[str, Any]:
    """
    Format a message into the format expected by Llama API.

    Args:
        message (Message): The message to format.
        openai_like (bool): Whether to format the message as an OpenAI-like message.

    Returns:
        Dict[str, Any]: The formatted message.
    """
    message_dict: Dict[str, Any] = {
        "role": ROLE_MAP[message.role] if not tool_calls else TOOL_CALL_ROLE_MAP[message.role],
        "content": [{"type": "text", "text": message.content or " "}],
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": message.tool_calls,
    }
    message_dict = {k: v for k, v in message_dict.items() if v is not None}

    if message.images is not None and len(message.images) > 0:
        for image in message.images:
            image_payload = process_image(image)
            if image_payload:
                message_dict["content"].append(image_payload)

    if message.videos is not None and len(message.videos) > 0:
        log_warning("Video input is currently unsupported.")

    if message.audio is not None and len(message.audio) > 0:
        log_warning("Audio input is currently unsupported.")

    if message.role == "tool":
        message_dict = {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }

    if message.role == "assistant":
        text_content = {"type": "text", "text": message.content or " "}

        if message.tool_calls is not None and len(message.tool_calls) > 0:
            message_dict = {
                "content": [text_content] if openai_like else text_content,
                "role": "assistant",
                "tool_calls": message.tool_calls,
                "stop_reason": "tool_calls",
            }
        else:
            message_dict = {
                "role": "assistant",
                "content": [text_content] if openai_like else text_content,
                "stop_reason": "stop",
            }

    return message_dict
