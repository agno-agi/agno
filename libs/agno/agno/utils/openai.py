import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from agno.media import Audio, File, Image
from agno.utils.log import log_error, log_warning

# Ensure .webp is recognized
mimetypes.add_type("image/webp", ".webp")


def audio_to_message(audio: Sequence[Audio]) -> List[Dict[str, Any]]:
    """
    Add audio to a message for the model. By default, we use the OpenAI audio format but other Models
    can override this method to use a different audio format.

    Args:
        audio: Pre-formatted audio data like {
                    "content": encoded_string,
                    "format": "wav"
                }

    Returns:
        Message content with audio added in the format expected by the model
    """
    from urllib.parse import urlparse

    audio_messages = []
    for audio_snippet in audio:
        encoded_string: Optional[str] = None
        audio_format: Optional[str] = audio_snippet.format

        # The audio is raw data
        if audio_snippet.content:
            encoded_string = base64.b64encode(audio_snippet.content).decode("utf-8")
            if not audio_format:
                audio_format = "wav"  # Default format if not provided

        # The audio is a URL
        elif audio_snippet.url:
            audio_bytes = audio_snippet.audio_url_content
            if audio_bytes is not None:
                encoded_string = base64.b64encode(audio_bytes).decode("utf-8")
                if not audio_format:
                    # Try to guess format from URL extension
                    try:
                        # Parse the URL first to isolate the path
                        parsed_url = urlparse(audio_snippet.url)
                        # Get suffix from the path component only
                        audio_format = Path(parsed_url.path).suffix.lstrip(".")
                        if not audio_format:  # Handle cases like URLs ending in /
                            log_warning(
                                f"Could not determine audio format from URL path: {parsed_url.path}. Defaulting."
                            )
                            audio_format = "wav"
                    except Exception as e:
                        log_warning(
                            f"Could not determine audio format from URL: {audio_snippet.url}. Error: {e}. Defaulting."
                        )
                        audio_format = "wav"  # Default if guessing fails

        # The audio is a file path
        elif audio_snippet.filepath:
            path = Path(audio_snippet.filepath)
            if path.exists() and path.is_file():
                try:
                    with open(path, "rb") as audio_file:
                        encoded_string = base64.b64encode(audio_file.read()).decode("utf-8")
                    if not audio_format:
                        audio_format = path.suffix.lstrip(".")
                except Exception as e:
                    log_error(f"Failed to read audio file {path}: {e}")
                    continue  # Skip this audio snippet if file reading fails
            else:
                log_error(f"Audio file not found or is not a file: {path}")
                continue  # Skip if file doesn't exist

        # Append the message if we successfully processed the audio
        if encoded_string and audio_format:
            audio_messages.append(
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": encoded_string,
                        "format": audio_format,
                    },
                },
            )
        else:
            log_error(f"Could not process audio snippet: {audio_snippet}")

    return audio_messages


def _process_bytes_image(image: bytes) -> Dict[str, Any]:
    """Process bytes image data."""
    base64_image = base64.b64encode(image).decode("utf-8")
    # Assuming JPEG if type not specified, could attempt detection
    image_url = f"data:image/jpeg;base64,{base64_image}"
    return {"type": "image_url", "image_url": {"url": image_url}}


def _process_image_path(image_path: Union[Path, str]) -> Dict[str, Any]:
    """Process image ( file path)."""
    # Process local file image
    path = Path(image_path)  # Ensure it's a Path object
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    if not path.is_file():
        raise IsADirectoryError(f"Image path is not a file: {image_path}")

    mime_type = mimetypes.guess_type(path)[0] or "image/jpeg"  # Default to jpeg if guess fails
    try:
        with open(path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")
            image_url = f"data:{mime_type};base64,{base64_image}"
            return {"type": "image_url", "image_url": {"url": image_url}}
    except Exception as e:
        log_error(f"Failed to read image file {path}: {e}")
        raise  # Re-raise the exception after logging


def _process_image_url(image_url: str) -> Dict[str, Any]:
    """Process image (base64 or URL)."""

    if image_url.startswith("data:image") or image_url.startswith(("http://", "https://")):
        return {"type": "image_url", "image_url": {"url": image_url}}
    else:
        raise ValueError("Image URL must start with 'data:image' or 'http(s)://'.")


def process_image(image: Image) -> Optional[Dict[str, Any]]:
    """Process an image based on the format."""
    image_payload: Optional[Dict[str, Any]] = None  # Initialize
    try:
        if image.url is not None:
            image_payload = _process_image_url(image.url)

        elif image.filepath is not None:
            image_payload = _process_image_path(image.filepath)

        elif image.content is not None:
            image_payload = _process_bytes_image(image.content)

        else:
            log_warning(f"Unsupported image format or no data provided: {image}")
            return None

        if image_payload and image.detail:  # Check if payload was created before adding detail
            # Ensure image_url key exists before trying to access its sub-dictionary
            if "image_url" not in image_payload:
                image_payload["image_url"] = {}  # Initialize if missing (though unlikely based on helper funcs)
            image_payload["image_url"]["detail"] = image.detail

        return image_payload

    except (FileNotFoundError, IsADirectoryError, ValueError) as e:
        log_error(f"Failed to process image due to invalid input: {str(e)}")
        return None  # Return None for handled validation errors
    except Exception as e:
        log_error(f"An unexpected error occurred while processing image: {str(e)}")
        # Depending on policy, you might want to return None or re-raise
        return None  # Return None for unexpected errors as well, preventing crashes


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
            image_data = process_image(image)
            if image_data:
                image_messages.append(image_data)
        except Exception as e:
            log_error(f"Failed to process image: {str(e)}")
            continue

    return image_messages


def _format_file_for_message(file: File) -> Optional[Dict[str, Any]]:
    """
    Add a document url, base64 encoded content or OpenAI file to a message.
    """
    import base64
    import mimetypes
    from pathlib import Path

    # Case 1: Document is a URL
    if file.url is not None:
        from urllib.parse import urlparse

        result = file.file_url_content
        if not result:
            log_error(f"Failed to fetch file from URL: {file.url}")
            return None
        content_bytes, mime_type = result
        name = Path(urlparse(file.url).path).name or "file"
        _mime = mime_type or file.mime_type or mimetypes.guess_type(name)[0] or "application/pdf"
        _encoded = base64.b64encode(content_bytes).decode("utf-8")
        _data_url = f"data:{_mime};base64,{_encoded}"
        return {"type": "file", "file": {"filename": name, "file_data": _data_url}}

    # Case 2: Document is a local file path
    if file.filepath is not None:
        path = Path(file.filepath)
        if not path.is_file():
            log_error(f"File not found: {path}")
            return None
        data = path.read_bytes()

        _mime = file.mime_type or mimetypes.guess_type(path.name)[0] or "application/pdf"
        _encoded = base64.b64encode(data).decode("utf-8")
        _data_url = f"data:{_mime};base64,{_encoded}"
        return {"type": "file", "file": {"filename": path.name, "file_data": _data_url}}

    # Case 3: Document is bytes content
    if file.content is not None:
        name = getattr(file, "filename", "file")
        _mime = file.mime_type or mimetypes.guess_type(name)[0] or "application/pdf"
        _encoded = base64.b64encode(file.content).decode("utf-8")
        _data_url = f"data:{_mime};base64,{_encoded}"
        return {"type": "file", "file": {"filename": name, "file_data": _data_url}}

    return None
