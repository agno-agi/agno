from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from agno.media import Audio, Image
from agno.models.message import Message
from agno.utils.log import logger


def add_audio_to_message(message: Message, audio: Sequence[Audio]) -> Message:
    """
    Add audio to a message for the model. By default, we use the OpenAI audio format but other Models
    can override this method to use a different audio format.

    Args:
        message: The message for the Model
        audio: Pre-formatted audio data like {
                    "content": encoded_string,
                    "format": "wav"
                }

    Returns:
        Message content with audio added in the format expected by the model
    """
    if len(audio) == 0:
        return message

    # Create a default message content with text
    message_content_with_audio: List[Dict[str, Any]] = [{"type": "text", "text": message.content}]

    for audio_snippet in audio:
        # The audio is raw data
        if audio_snippet.content:
            import base64

            encoded_string = base64.b64encode(audio_snippet.content).decode("utf-8")

            # Create a message with audio
            message_content_with_audio.append(
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": encoded_string,
                        "format": audio_snippet.format,
                    },
                },
            )
        if audio_snippet.url:
            # The audio is a URL
            import base64

            audio_bytes = audio_snippet.audio_url_content
            if audio_bytes is not None:
                encoded_string = base64.b64encode(audio_bytes).decode("utf-8")

                message_content_with_audio.append(
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": encoded_string,
                            "format": audio_snippet.format,
                        },
                    },
                )

        if audio_snippet.filepath:
            # The audio is a file path
            import base64

            path = Path(audio_snippet.filepath) if isinstance(audio_snippet.filepath, str) else audio_snippet.filepath
            if path.exists() and path.is_file():
                with open(audio_snippet.filepath, "rb") as audio_file:
                    encoded_string = base64.b64encode(audio_file.read()).decode("utf-8")

            message_content_with_audio.append(
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": encoded_string,
                        "format": audio_snippet.format,
                    },
                },
            )

    # Update the message content with the audio
    message.content = message_content_with_audio
    message.audio = None  # The message should not have an audio component after this

    return message


def _process_bytes_image(image: bytes) -> Dict[str, Any]:
    """Process bytes image data."""
    import base64

    base64_image = base64.b64encode(image).decode("utf-8")
    image_url = f"data:image/jpeg;base64,{base64_image}"
    return {"type": "image_url", "image_url": {"url": image_url}}


def _process_image_path(image_path: Union[Path, str]) -> Dict[str, Any]:
    """Process image ( file path)."""
    # Process local file image
    import base64
    import mimetypes

    path = image_path if isinstance(image_path, Path) else Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode("utf-8")
        image_url = f"data:{mime_type};base64,{base64_image}"
        return {"type": "image_url", "image_url": {"url": image_url}}


def _process_image_url(image_url: str) -> Dict[str, Any]:
    """Process image (base64 or URL)."""

    if image_url.startswith("data:image") or image_url.startswith(("http://", "https://")):
        return {"type": "image_url", "image_url": {"url": image_url}}
    else:
        raise ValueError("Image URL must start with 'data:image' or 'http(s)://'.")


def _process_image(image: Image) -> Optional[Dict[str, Any]]:
    """Process an image based on the format."""

    if image.url is not None:
        image_payload = _process_image_url(image.url)

    elif image.filepath is not None:
        image_payload = _process_image_path(image.filepath)

    elif image.content is not None:
        image_payload = _process_bytes_image(image.content)

    else:
        logger.warning(f"Unsupported image type: {type(image)}")
        return None

    if image.detail:
        image_payload["image_url"]["detail"] = image.detail

    return image_payload


def add_images_to_message(message: Message, images: Sequence[Image]) -> Message:
    """
    Add images to a message for the model. By default, we use the OpenAI image format but other Models
    can override this method to use a different image format.

    Args:
        message: The message for the Model
        images: Sequence of images in various formats:
            - str: base64 encoded image, URL, or file path
            - Dict: pre-formatted image data
            - bytes: raw image data

    Returns:
        Message content with images added in the format expected by the model
    """
    # If no images are provided, return the message as is
    if len(images) == 0:
        return message

    # Ignore non-string message content
    # because we assume that the images/audio are already added to the message
    if not isinstance(message.content, str):
        return message

    # Create a default message content with text
    message_content_with_image: List[Dict[str, Any]] = [{"type": "text", "text": message.content}]

    # Add images to the message content
    for image in images:
        try:
            image_data = _process_image(image)
            if image_data:
                message_content_with_image.append(image_data)
        except Exception as e:
            logger.error(f"Failed to process image: {str(e)}")
            continue

    # Update the message content with the images
    message.content = message_content_with_image
    return message
