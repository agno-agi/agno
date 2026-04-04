import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from agno.media import Audio, File, Image
from agno.utils.log import log_error, log_warning
from agno.utils.media import resolve_image_mime_type


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
            audio_bytes = audio_snippet.get_content_bytes()
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


def _process_bytes_image(
    image: bytes, mime_type: Optional[str] = None, image_format: Optional[str] = None
) -> Dict[str, Any]:
    base64_image = base64.b64encode(image).decode("utf-8")
    resolved_mime = resolve_image_mime_type(mime_type=mime_type, image_format=image_format, image_bytes=image)
    image_url = f"data:{resolved_mime};base64,{base64_image}"
    return {"type": "image_url", "image_url": {"url": image_url}}


def _process_image_path(
    image_path: Union[Path, str], mime_type: Optional[str] = None, image_format: Optional[str] = None
) -> Dict[str, Any]:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")
    if not path.is_file():
        raise IsADirectoryError(f"Image path is not a file: {image_path}")

    try:
        with open(path, "rb") as image_file:
            image_data = image_file.read()
    except Exception as e:
        log_error(f"Failed to read image file {path}: {e}")
        raise

    base64_image = base64.b64encode(image_data).decode("utf-8")
    resolved_mime = resolve_image_mime_type(
        mime_type=mime_type, image_format=image_format, file_path=path, image_bytes=image_data
    )
    image_url = f"data:{resolved_mime};base64,{base64_image}"
    return {"type": "image_url", "image_url": {"url": image_url}}


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
            image_payload = _process_image_path(image.filepath, mime_type=image.mime_type, image_format=image.format)

        elif image.content is not None:
            image_payload = _process_bytes_image(image.content, mime_type=image.mime_type, image_format=image.format)

        else:
            log_warning(f"Unsupported image format or no data provided: {image}")
            return None

        if image_payload and image.detail:
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


def _extract_text_from_file(content: bytes, mime_type: Optional[str], filename: Optional[str]) -> Optional[str]:
    """Extract plain text from file content based on MIME type.

    Returns extracted text, or ``None`` if the format is unsupported or
    extraction fails.  Libraries for PDF and DOCX are imported lazily so
    they remain optional dependencies.
    """
    if mime_type is None and filename:
        mime_type = mimetypes.guess_type(filename)[0]

    if mime_type is None:
        return None

    # Text-based MIME types: decode directly
    _text_mime_types = {
        "text/plain",
        "text/csv",
        "text/html",
        "text/css",
        "text/xml",
        "text/rtf",
        "text/md",
        "text/markdown",
        "text/javascript",
        "application/json",
        "application/x-javascript",
        "application/x-python",
        "text/x-python",
    }
    if mime_type in _text_mime_types or mime_type.startswith("text/"):
        try:
            return content.decode("utf-8", errors="replace")
        except Exception:
            return None

    # PDF extraction via pypdf
    if mime_type == "application/pdf":
        try:
            from io import BytesIO

            from pypdf import PdfReader

            reader = PdfReader(BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(pages).strip()
            return text if text else None
        except Exception:
            return None

    # DOCX extraction via python-docx
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            from io import BytesIO

            from docx import Document as DocxDocument  # type: ignore

            doc = DocxDocument(BytesIO(content))
            text = "\n\n".join(para.text for para in doc.paragraphs).strip()
            return text if text else None
        except Exception:
            return None

    return None


def _format_file_for_message(file: File, extract_text: bool = False) -> Optional[Dict[str, Any]]:
    """
    Add a document url, base64 encoded content or OpenAI file to a message.

    When *extract_text* is ``True``, the function attempts to extract plain
    text from the file and returns a ``{"type": "text", ...}`` content block
    instead of ``{"type": "file", ...}``.  This is useful for models that do
    not support the ``file`` content type (e.g. ``gpt-4.1-mini`` via Azure).
    Falls back to the standard ``file`` format if extraction fails.
    """
    import base64
    import mimetypes
    from pathlib import Path

    # When extract_text is requested, try to extract text first
    if extract_text:
        content_bytes: Optional[bytes] = None
        _filename: Optional[str] = file.filename
        _mime: Optional[str] = file.mime_type

        if file.url is not None:
            from urllib.parse import urlparse

            result = file.file_url_content
            if result:
                content_bytes, url_mime = result
                _filename = _filename or Path(urlparse(file.url).path).name or "file"
                _mime = _mime or url_mime
        elif file.filepath is not None:
            path = Path(file.filepath)
            if path.is_file():
                content_bytes = path.read_bytes()
                _filename = _filename or path.name
                _mime = _mime or mimetypes.guess_type(path.name)[0]
        elif file.content is not None:
            content_bytes = file.content if isinstance(file.content, bytes) else file.content.encode("utf-8")
            _filename = _filename or "file"

        if content_bytes is not None:
            extracted = _extract_text_from_file(content_bytes, _mime, _filename)
            if extracted is not None:
                display_name = _filename or "file"
                return {"type": "text", "text": f"[File: {display_name}]\n{extracted}"}

    # Case 1: Document is a URL
    if file.url is not None:
        from urllib.parse import urlparse

        result = file.file_url_content
        if not result:
            log_error(f"Failed to fetch file from URL: {file.url}")
            return None
        content_bytes_url, mime_type = result
        name = Path(urlparse(file.url).path).name or "file"
        _mime_url = mime_type or file.mime_type or mimetypes.guess_type(name)[0] or "application/pdf"
        _encoded = base64.b64encode(content_bytes_url).decode("utf-8")
        _data_url = f"data:{_mime_url};base64,{_encoded}"
        return {"type": "file", "file": {"filename": name, "file_data": _data_url}}

    # Case 2: Document is a local file path
    if file.filepath is not None:
        path = Path(file.filepath)
        if not path.is_file():
            log_error(f"File not found: {path}")
            return None
        data = path.read_bytes()

        _mime_path = file.mime_type or mimetypes.guess_type(path.name)[0] or "application/pdf"
        _encoded = base64.b64encode(data).decode("utf-8")
        _data_url = f"data:{_mime_path};base64,{_encoded}"
        return {"type": "file", "file": {"filename": path.name, "file_data": _data_url}}

    # Case 3: Document is bytes content
    if file.content is not None:
        name = file.filename or "file"
        _mime_bytes = file.mime_type or mimetypes.guess_type(name)[0] or "application/pdf"
        _encoded = base64.b64encode(file.content).decode("utf-8")
        _data_url = f"data:{_mime_bytes};base64,{_encoded}"
        return {"type": "file", "file": {"filename": name, "file_data": _data_url}}

    return None
