from typing import Any, Dict, List, Sequence

from agno.media import Image
from agno.models.message import Message
from agno.utils.log import log_error, log_warning


def format_images_for_message(message: Message, images: Sequence[Image]) -> Message:
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
    if len(message_content_with_image) > 1:
        message.content = message_content_with_image
    return message
