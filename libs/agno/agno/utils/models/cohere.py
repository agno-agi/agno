from pathlib import Path
from typing import Any, Dict, List, Sequence

from agno.media import Image
from agno.models.message import Message
from agno.utils.log import log_error, log_warning


def _format_images_for_message(message: Message, images: Sequence[Image]) -> List[Dict[str, Any]]:
    """
    Format an image into the format expected by WatsonX.
    """

    # Create a default message content with text
    message_content_with_image: List[Dict[str, Any]] = [{"type": "text", "text": message.content}]

    # Add images to the message content
    for image in images:
        try:
            if image.content is not None:
                image_content = image.content
            elif image.url is not None:
                image_content = image.image_url_content
            elif image.filepath is not None:
                if isinstance(image.filepath, Path):
                    image_content = image.filepath.read_bytes()
                else:
                    with open(image.filepath, "rb") as f:
                        image_content = f.read()
            else:
                log_warning(f"Unsupported image format: {image}")
                continue

            if image_content is not None:
                import base64

                base64_image = base64.b64encode(image_content).decode("utf-8")
                image_url = f"data:image/jpeg;base64,{base64_image}"
                image_payload = {"type": "image_url", "image_url": {"url": image_url}}
                message_content_with_image.append(image_payload)

        except Exception as e:
            log_error(f"Failed to process image: {str(e)}")

    # Update the message content with the images
    return message_content_with_image


def format_messages(messages: List[Message]) -> List[Dict[str, Any]]:
    """
    Format messages for the Cohere API.

    Args:
        messages (List[Message]): The list of messages.

    Returns:
        List[Dict[str, Any]]: The formatted messages.
    """
    formatted_messages = []
    for message in messages:
        message_dict = {
            "role": message.role,
            "content": message.content,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }

        if message.images is not None and len(message.images) > 0:
            # Ignore non-string message content
            if isinstance(message.content, str):
                message_content_with_image = _format_images_for_message(message=message, images=message.images)
                if len(message_content_with_image) > 1:
                    message_dict["content"] = message_content_with_image

        if message.videos is not None and len(message.videos) > 0:
            log_warning("Video input is currently unsupported.")

        if message.audio is not None and len(message.audio) > 0:
            log_warning("Audio input is currently unsupported.")

        if message.files is not None and len(message.files) > 0:
            log_warning("File input is currently unsupported.")

        message_dict = {k: v for k, v in message_dict.items() if v is not None}
        formatted_messages.append(message_dict)
    return formatted_messages
