from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from agno.media import Image
from agno.utils.log import logger
from agno.utils.media import resolve_image_mime_type


def _process_bytes_image(
    image: bytes, mime_type: Optional[str] = None, image_format: Optional[str] = None
) -> Dict[str, Any]:
    """Process bytes image data."""
    import base64

    base64_image = base64.b64encode(image).decode("utf-8")
    resolved_mime = resolve_image_mime_type(mime_type=mime_type, image_format=image_format, image_bytes=image)
    image_url = f"data:{resolved_mime};base64,{base64_image}"
    return {"type": "input_image", "image_url": image_url}


def _process_image_path(
    image_path: Union[Path, str], mime_type: Optional[str] = None, image_format: Optional[str] = None
) -> Dict[str, Any]:
    """Process image from file path."""
    import base64

    path = image_path if isinstance(image_path, Path) else Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    with open(path, "rb") as image_file:
        image_data = image_file.read()

    base64_image = base64.b64encode(image_data).decode("utf-8")
    resolved_mime = resolve_image_mime_type(
        mime_type=mime_type, image_format=image_format, file_path=path, image_bytes=image_data
    )
    image_url = f"data:{resolved_mime};base64,{base64_image}"
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
        image_payload = _process_image_path(image.filepath, mime_type=image.mime_type, image_format=image.format)

    elif image.content is not None:
        image_payload = _process_bytes_image(image.content, mime_type=image.mime_type, image_format=image.format)

    else:
        logger.warning(f"Unsupported image format: {image}")
        return None

    # Responses API puts detail at top level, not nested under image_url like Chat API
    if image_payload and image.detail:
        image_payload["detail"] = image.detail

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
        except Exception:
            logger.exception("Failed to process image")
            continue

    return image_messages


def sanitize_response_schema(schema: dict):
    """
    Recursively sanitize a Pydantic-generated JSON schema to comply with OpenAI's response_format rules:

    - Sets "additionalProperties": false for all object types to disallow extra fields,
      EXCEPT when additionalProperties is already defined with a schema (Dict types).
    - Removes "default": null from optional fields.
    - Ensures that all fields defined in "properties" are listed in "required",
      making every property explicitly required as per OpenAI's expectations,
      EXCEPT for Dict fields which should not be in the required array.
    """
    if isinstance(schema, dict):
        # Enforce additionalProperties: false for object types, but preserve Dict schemas
        if schema.get("type") == "object":
            # Only set additionalProperties to False if it's not already defined with a schema
            # This preserves Dict[str, T] fields which need additionalProperties to define value types
            if "additionalProperties" not in schema:
                schema["additionalProperties"] = False
            elif schema.get("additionalProperties") is True:
                # Convert True to False for strict mode, but preserve schema objects
                schema["additionalProperties"] = False

            # Ensure all properties are required, EXCEPT Dict fields
            if "properties" in schema:
                from agno.utils.models.schema_utils import is_dict_field

                required_fields = []
                for prop_name, prop_schema in schema["properties"].items():
                    # Use the utility function to check if this is a Dict field
                    if not is_dict_field(prop_schema):
                        required_fields.append(prop_name)

                schema["required"] = required_fields

        # Remove only default: null
        if "default" in schema and schema["default"] is None:
            schema.pop("default")

        # Recurse into all values
        for value in schema.values():
            sanitize_response_schema(value)

    elif isinstance(schema, list):
        for item in schema:
            sanitize_response_schema(item)
