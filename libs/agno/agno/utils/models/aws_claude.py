import json
from typing import Any, Dict, List, Optional, Tuple

from agno.media import Image
from agno.models.message import Message
from agno.utils.log import log_error, log_warning

try:
    from anthropic.types import (
        TextBlock,
        ToolUseBlock,
    )
except ImportError:
    log_error("`anthropic[bedrock]` not installed. Please install it via `pip install anthropic[bedrock]`.")
    raise

ROLE_MAP = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "user",
}


def _format_image_for_message(image: Image) -> Optional[Dict[str, Any]]:
    """
    Add an image to a message by converting it to base64 encoded format.
    """
    using_filetype = False

    import base64

    # 'imghdr' was deprecated in Python 3.11: https://docs.python.org/3/library/imghdr.html
    # 'filetype' used as a fallback
    try:
        import imghdr
    except (ModuleNotFoundError, ImportError):
        try:
            import filetype

            using_filetype = True
        except (ModuleNotFoundError, ImportError):
            raise ImportError("`filetype` not installed. Please install using `pip install filetype`")

    type_mapping = {
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }

    try:
        # Case 1: Image is a URL
        if image.url is not None:
            content_bytes = image.image_url_content

        # Case 2: Image is a local file path
        elif image.filepath is not None:
            from pathlib import Path

            path = Path(image.filepath) if isinstance(image.filepath, str) else image.filepath
            if path.exists() and path.is_file():
                with open(image.filepath, "rb") as f:
                    content_bytes = f.read()
            else:
                log_error(f"Image file not found: {image}")
                return None

        # Case 3: Image is a bytes object
        elif image.content is not None:
            content_bytes = image.content

        else:
            log_error(f"Unsupported image type: {type(image)}")
            return None

        if using_filetype:
            kind = filetype.guess(content_bytes)
            if not kind:
                log_error("Unable to determine image type")
                return None

            img_type = kind.extension
        else:
            img_type = imghdr.what(None, h=content_bytes)  # type: ignore

        if not img_type:
            log_error("Unable to determine image type")
            return None

        media_type = type_mapping.get(img_type)
        if not media_type:
            log_error(f"Unsupported image type: {img_type}")
            return None

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(content_bytes).decode("utf-8"),  # type: ignore
            },
        }

    except Exception as e:
        log_error(f"Error processing image: {e}")
        return None


def format_messages(messages: List[Message]) -> Tuple[List[Dict[str, str]], str]:
    """
    Process the list of messages and separate them into API messages and system messages.

    Args:
        messages (List[Message]): The list of messages to process.

    Returns:
        Tuple[List[Dict[str, str]], str]: A tuple containing the list of API messages and the concatenated system messages.
    """

    chat_messages: List[Dict[str, str]] = []
    system_messages: List[str] = []

    for message in messages:
        content = message.content or ""
        if message.role == "system":
            if content is not None:
                system_messages.append(content)  # type: ignore
            continue
        elif message.role == "user":
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]

            if message.images is not None:
                for image in message.images:
                    image_content = _format_image_for_message(image)
                    if image_content:
                        content.append(image_content)

            if message.files is not None and len(message.files) > 0:
                log_warning("Files are not supported for AWS Bedrock Claude")

            if message.audio is not None and len(message.audio) > 0:
                log_warning("Audio is not supported for AWS Bedrock Claude")

            if message.videos is not None and len(message.videos) > 0:
                log_warning("Video is not supported for AWS Bedrock Claude")

        # Handle tool calls from history
        elif message.role == "assistant":
            content = []

            if isinstance(message.content, str) and message.content and len(message.content.strip()) > 0:
                content.append(TextBlock(text=message.content, type="text"))

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    content.append(
                        ToolUseBlock(
                            id=tool_call["id"],
                            input=json.loads(tool_call["function"]["arguments"])
                            if "arguments" in tool_call["function"]
                            else {},
                            name=tool_call["function"]["name"],
                            type="tool_use",
                        )
                    )
        chat_messages.append({"role": ROLE_MAP[message.role], "content": content})  # type: ignore
    return chat_messages, " ".join(system_messages)
