from typing import Any, Dict

from agno.models.message import Message
from agno.utils.log import log_warning
from agno.utils.openai import images_to_message


def format_message(message: Message) -> Dict[str, Any]:
    """
    Format a message into the format expected by OpenAI.

    Args:
        message (Message): The message to format.

    Returns:
        Dict[str, Any]: The formatted message.
    """
    message_dict: Dict[str, Any] = {
        "role": message.role,
        "content": message.content,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": message.tool_calls,
    }
    message_dict = {k: v for k, v in message_dict.items() if v is not None}

    if message.images is not None and len(message.images) > 0:
        # Ignore non-string message content
        # because we assume that the images/audio are already added to the message
        if isinstance(message.content, str):
            message_dict["content"] = [{"type": "text", "text": message.content}]
            message_dict["content"].extend(images_to_message(images=message.images))

    if message.audio is not None and len(message.audio) > 0:
        log_warning("Audio input is currently unsupported.")

    if message.files is not None and len(message.files) > 0:
        log_warning("File input is currently unsupported.")

    if message.videos is not None and len(message.videos) > 0:
        log_warning("Video input is currently unsupported.")

    return message_dict
