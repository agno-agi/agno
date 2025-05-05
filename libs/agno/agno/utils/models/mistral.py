from typing import Any, List, Optional, Union

from agno.media import Image
from agno.models.message import Message
from agno.utils.log import log_error, log_warning

try:
    from mistralai.models import (
        AssistantMessage,
        ImageURLChunk,
        SystemMessage,
        TextChunk,
        ToolMessage,
        UserMessage,
    )

    MistralMessage = Union[UserMessage, AssistantMessage, SystemMessage, ToolMessage]

except ImportError:
    raise ImportError("`mistralai` not installed. Please install using `pip install mistralai`")


def _format_image_for_message(image: Image) -> Optional[ImageURLChunk]:
    # Case 1: Image is a URL
    if image.url is not None:
        return ImageURLChunk(image_url=image.url)
    # Case 2: Image is a local file path
    elif image.filepath is not None:
        import base64
        from pathlib import Path

        path = Path(image.filepath) if isinstance(image.filepath, str) else image.filepath
        if not path.exists() or not path.is_file():
            log_error(f"Image file not found: {image}")
            raise FileNotFoundError(f"Image file not found: {image}")

        with open(image.filepath, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")
            return ImageURLChunk(image_url=f"data:image/jpeg;base64,{base64_image}")

    # Case 3: Image is a bytes object
    elif image.content is not None:
        import base64

        base64_image = base64.b64encode(image.content).decode("utf-8")
        return ImageURLChunk(image_url=f"data:image/jpeg;base64,{base64_image}")
    return None


def format_messages(messages: List[Message]) -> List[MistralMessage]:
    mistral_messages: List[MistralMessage] = []

    for message in messages:
        mistral_message: MistralMessage
        if message.role == "user":
            if message.audio is not None and len(message.audio) > 0:
                log_warning("Audio input is currently unsupported.")

            if message.files is not None and len(message.files) > 0:
                log_warning("File input is currently unsupported.")

            if message.videos is not None and len(message.videos) > 0:
                log_warning("Video input is currently unsupported.")

            if message.images is not None:
                content: List[Any] = [TextChunk(type="text", text=message.content)]
                for image in message.images:
                    image_content = _format_image_for_message(image)
                    if image_content:
                        content.append(image_content)
                mistral_message = UserMessage(role="user", content=content)
            else:
                mistral_message = UserMessage(role="user", content=message.content)
        elif message.role == "assistant":
            if message.reasoning_content is not None:
                mistral_message = UserMessage(role="user", content=message.content)
            elif message.tool_calls is not None:
                mistral_message = AssistantMessage(
                    role="assistant", content=message.content, tool_calls=message.tool_calls
                )
            else:
                mistral_message = AssistantMessage(role=message.role, content=message.content)
        elif message.role == "system":
            mistral_message = SystemMessage(role="system", content=message.content)
        elif message.role == "tool":
            mistral_message = ToolMessage(name="tool", content=message.content, tool_call_id=message.tool_call_id)
        else:
            raise ValueError(f"Unknown role: {message.role}")

        mistral_messages.append(mistral_message)

    # Check if the last message is an assistant message
    if mistral_messages and hasattr(mistral_messages[-1], "role") and mistral_messages[-1].role == "assistant":
        # Set prefix=True for the last assistant message to allow it as the last message
        mistral_messages[-1].prefix = True

    return mistral_messages
