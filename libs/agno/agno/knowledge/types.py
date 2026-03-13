from enum import Enum
from typing import Any

from pydantic import BaseModel


class ContentType(str, Enum):
    """Enum for content types supported by knowledge readers."""

    # Generic types
    FILE = "file"
    URL = "url"
    TEXT = "text"
    TOPIC = "topic"
    YOUTUBE = "youtube"

    # Document file extensions
    PDF = ".pdf"
    TXT = ".txt"
    MARKDOWN = ".md"
    DOCX = ".docx"
    DOC = ".doc"
    PPTX = ".pptx"
    JSON = ".json"
    VTT = ".vtt"

    # Image formats
    IMAGE_PNG = ".png"
    IMAGE_JPEG = ".jpeg"
    IMAGE_JPG = ".jpg"
    IMAGE_TIFF = ".tiff"
    IMAGE_TIF = ".tif"
    IMAGE_BMP = ".bmp"
    IMAGE_WEBP = ".webp"

    # Spreadsheet file extensions
    CSV = ".csv"
    XLSX = ".xlsx"
    XLS = ".xls"

    # Audio formats
    AUDIO_WAV = ".wav"
    AUDIO_MP3 = ".mp3"
    AUDIO_M4A = ".m4a"
    AUDIO_AAC = ".aac"
    AUDIO_OGG = ".ogg"
    AUDIO_FLAC = ".flac"
    AUDIO_MP4 = ".mp4"
    AUDIO_AVI = ".avi"
    AUDIO_MOV = ".mov"


def get_content_type_enum(content_type_str: str) -> ContentType:
    """Convert a content type string to ContentType enum."""
    return ContentType(content_type_str)


class KnowledgeFilter(BaseModel):
    key: str
    value: Any
