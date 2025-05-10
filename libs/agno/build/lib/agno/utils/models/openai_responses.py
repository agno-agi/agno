from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from agno.media import Image
from agno.utils.log import logger


def _process_bytes_image(image: bytes) -> Dict[str, Any]:
    """Process bytes image data."""
    import base64

    base64_image = base64.b64encode(image).decode("utf-8")
    image_url = f"data:image/jpeg;base64,{base64_image}"
    return {"type": "input_image", "image_url": image_url}


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
        return {"type": "input_image", "image_url": image_url}


def _process_image_url(image_url: str) -> Dict[str, Any]:
    """Process image (base64 or URL)."""

    if image_url.startswith("data:image") or image_url.startswith(("http://", "https://")):
        return {"type": "input_image", "image_url": image_url}
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
        logger.warning(f"Unsupported image format: {image}")
        return None

    if image.detail:
        image_payload["image_url"]["detail"] = image.detail

    return image_payload


def images_to_message(images: Sequence[Image]) -> List[Dict[str, Any]]:
    """
    Add images to a message for the model. By default, we use the OpenAI image format but other Models
    can override this method to use a different image format.

    Args:
        images: Sequence of images in various formats:
            - str: base64 encoded image, URL, or file path
            - Dict: pre-formatted image data
            - bytes: raw image data

    Returns:
        Message content with images added in the format expected by the model
    """

    # Create a default message content with text
    image_messages: List[Dict[str, Any]] = []

    # Add images to the message content
    for image in images:
        try:
            image_data = _process_image(image)
            if image_data:
                image_messages.append(image_data)
        except Exception as e:
            logger.error(f"Failed to process image: {str(e)}")
            continue

    return image_messages


def sanitize_response_schema(schema: dict):
    """
    Recursively sanitize a Pydantic-generated JSON schema to comply with OpenAI's response_format rules:

    - Sets "additionalProperties": false for all object types to disallow extra fields.
    - Removes "default": null from optional fields.
    - Ensures that all fields defined in "properties" are listed in "required",
      making every property explicitly required as per OpenAI's expectations.
    """
    if isinstance(schema, dict):
        # Enforce additionalProperties: false
        if schema.get("type") == "object":
            schema["additionalProperties"] = False

            # Ensure all properties are required
            if "properties" in schema:
                schema["required"] = list(schema["properties"].keys())

        # Remove only default: null
        if "default" in schema and schema["default"] is None:
            schema.pop("default")

        # Recurse into all values
        for value in schema.values():
            sanitize_response_schema(value)

    elif isinstance(schema, list):
        for item in schema:
            sanitize_response_schema(item)
