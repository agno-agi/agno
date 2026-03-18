import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from agno.media import File, Image
from agno.models.message import Message
from agno.utils.log import log_error, log_warning

try:
    from anthropic.types import (
        TextBlock,
        ToolUseBlock,
    )
except ImportError:
    raise ImportError("`anthropic` not installed. Please install using `pip install anthropic`")


@dataclass
class MCPToolConfiguration:
    enabled: bool = True
    allowed_tools: List[str] = field(default_factory=list)


@dataclass
class MCPServerConfiguration:
    type: str
    url: str
    name: str
    tool_configuration: Optional[MCPToolConfiguration] = None
    authorization_token: Optional[str] = None


ROLE_MAP = {
    "system": "system",
    "developer": "system",
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
    except ImportError:
        try:
            import filetype

            using_filetype = True
        except ImportError:
            raise ImportError("`filetype` not installed. Please install using `pip install filetype`")

    type_mapping = {
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }

    try:
        img_type = None

        # Case 0: Image is an Anthropic uploaded file
        if image.content is not None and hasattr(image.content, "id"):
            content_bytes = image.content

        # Case 1: Image is a URL
        if image.url is not None:
            content_bytes = image.get_content_bytes()  # type: ignore

            # If image URL has a suffix, use it as the type (without dot)
            import os
            from urllib.parse import urlparse

            if image.url:
                parsed_url = urlparse(image.url)
                _, ext = os.path.splitext(parsed_url.path)
                if ext:
                    img_type = ext.lstrip(".").lower()

        # Case 2: Image is a local file path
        elif image.filepath is not None:
            from pathlib import Path

            path = Path(image.filepath) if isinstance(image.filepath, str) else image.filepath
            if path.exists() and path.is_file():
                with open(image.filepath, "rb") as f:
                    content_bytes = f.read()

                # If image file path has a suffix, use it as the type (without dot)
                path_ext = path.suffix.lstrip(".")
                if path_ext:
                    img_type = path_ext.lower()
            else:
                log_error(f"Image file not found: {image}")
                return None

        # Case 3: Image is a bytes object
        elif image.content is not None:
            content_bytes = image.content

        else:
            log_error(f"Unsupported image type: {type(image)}")
            return None

        if not img_type:
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


def _format_file_for_message(file: File) -> Optional[Dict[str, Any]]:
    """
    Add a document url or base64 encoded content to a message.
    """

    mime_mapping: dict[str, str] = {
        "application/pdf": "base64",
        # All text/* MIME types use the "text" source type
        "text/plain": "text",
        "text/csv": "text",
        "text/html": "text",
        "text/css": "text",
        "text/md": "text",
        "text/xml": "text",
        "text/rtf": "text",
        "text/javascript": "text",
        "text/x-python": "text",
        "application/json": "text",
        "application/x-javascript": "text",
        "application/x-python": "text",
    }

    # Case 0: File is an Anthropic uploaded file
    if file.external is not None and hasattr(file.external, "id"):
        return {
            "type": "document",
            "source": {
                "type": "file",
                "file_id": file.external.id,
            },
        }

    # Case 1: Document is a URL
    if file.url is not None:
        return {
            "type": "document",
            "source": {
                "type": "url",
                "url": file.url,
            },
            "citations": {"enabled": True},
        }
    # Case 2: Document is a local file path
    elif file.filepath is not None:
        import base64
        from pathlib import Path

        path = Path(file.filepath) if isinstance(file.filepath, str) else file.filepath
        if path.exists() and path.is_file():
            raw_bytes = path.read_bytes()

            # Determine media type
            media_type = file.mime_type
            if media_type is None:
                import mimetypes

                media_type = mimetypes.guess_type(file.filepath)[0] or "application/pdf"

            # Map media type to source type, default to "base64" if no mapping exists
            source_type = mime_mapping.get(media_type, "base64")

            if source_type == "text":
                return {
                    "type": "document",
                    "source": {
                        "type": "text",
                        "media_type": "text/plain",
                        "data": raw_bytes.decode("utf-8", errors="replace"),
                    },
                    "citations": {"enabled": True},
                }
            else:
                return {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.standard_b64encode(raw_bytes).decode("utf-8"),
                    },
                    "citations": {"enabled": True},
                }
        else:
            log_error(f"Document file not found: {file}")
            return None
    # Case 3: Document is bytes content
    elif file.content is not None:
        media_type = file.mime_type or "application/pdf"
        # Map media type to source type, default to "base64" if no mapping exists
        source_type = mime_mapping.get(media_type, "base64")

        if source_type == "text":
            return {
                "type": "document",
                "source": {
                    "type": "text",
                    "media_type": "text/plain",
                    "data": file.content.decode("utf-8", errors="replace"),
                },
                "citations": {"enabled": True},
            }
        else:
            import base64

            return {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(file.content).decode("utf-8"),
                },
                "citations": {"enabled": True},
            }
    return None


def format_messages(
    messages: List[Message], compress_tool_results: bool = False
) -> Tuple[List[Dict[str, Union[str, list]]], str]:
    """
    Process the list of messages and separate them into API messages and system messages.

    Args:
        messages (List[Message]): The list of messages to process.
        compress_tool_results: Whether to compress tool results.

    Returns:
        Tuple[List[Dict[str, Union[str, list]]], str]: A tuple containing the list of API messages and the concatenated system messages.
    """
    chat_messages: List[Dict[str, Union[str, list]]] = []
    system_messages: List[str] = []

    for message in messages:
        content = message.content or ""
        # Both "system" and "developer" roles should be extracted as system messages
        if message.role in ("system", "developer"):
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

            if message.files is not None:
                for file in message.files:
                    file_content = _format_file_for_message(file)
                    if file_content:
                        content.append(file_content)

            if message.audio is not None and len(message.audio) > 0:
                log_warning("Audio input is currently unsupported.")

            if message.videos is not None and len(message.videos) > 0:
                log_warning("Video input is currently unsupported.")

        elif message.role == "assistant":
            content = []

            if message.reasoning_content is not None and message.provider_data is not None:
                from anthropic.types import RedactedThinkingBlock, ThinkingBlock

                content.append(
                    ThinkingBlock(
                        thinking=message.reasoning_content,
                        signature=message.provider_data.get("signature"),
                        type="thinking",
                    )
                )

            if message.redacted_reasoning_content is not None:
                from anthropic.types import RedactedThinkingBlock

                content.append(
                    RedactedThinkingBlock(data=message.redacted_reasoning_content, type="redacted_reasoning_content")
                )

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
        elif message.role == "tool":
            content = []

            # Use compressed content for tool messages if compression is active
            tool_result = message.get_content(use_compressed_content=compress_tool_results)

            content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": str(tool_result),
                }
            )

        # Skip empty assistant responses
        if message.role == "assistant" and not content:
            continue

        chat_messages.append({"role": ROLE_MAP[message.role], "content": content})  # type: ignore
    return chat_messages, " ".join(system_messages)


def format_tools_for_model(tools: Optional[List[Dict[str, Any]]] = None) -> Optional[List[Dict[str, Any]]]:
    """
    Transforms function definitions into a format accepted by the Anthropic API.
    Now supports strict mode for structured outputs.
    """
    if not tools:
        return None

    parsed_tools: List[Dict[str, Any]] = []
    for tool_def in tools:
        if tool_def.get("type", "") != "function":
            parsed_tools.append(tool_def)
            continue

        func_def = tool_def.get("function", {})
        parameters: Dict[str, Any] = func_def.get("parameters", {})
        properties: Dict[str, Any] = parameters.get("properties", {})
        required: List[str] = parameters.get("required", [])
        required_params: List[str] = required

        input_properties: Dict[str, Any] = {}
        for param_name, param_info in properties.items():
            # Preserve the complete schema structure for complex types
            input_properties[param_name] = param_info.copy()

            # Ensure description is present (default to empty if missing)
            if "description" not in input_properties[param_name]:
                input_properties[param_name]["description"] = ""

        tool = {
            "name": func_def.get("name") or "",
            "description": func_def.get("description") or "",
            "input_schema": {
                "type": parameters.get("type", "object"),
                "properties": input_properties,
                "required": required_params,
                "additionalProperties": False,
            },
        }

        # Add strict mode if specified (check both function dict and tool_def top level)
        strict_mode = func_def.get("strict") or tool_def.get("strict")
        if strict_mode is True:
            tool["strict"] = True

        parsed_tools.append(tool)
    return parsed_tools
