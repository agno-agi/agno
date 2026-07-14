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
    DOC = ".doc"
    JSON = ".json"
    VTT = ".vtt"
    MARKDOWN = ".md"

    DOCX = ".docx"
    DOTX = ".dotx"
    DOCM = ".docm"
    DOTM = ".dotm"

    PPTX = ".pptx"
    POTX = ".potx"
    PPSX = ".ppsx"
    POTM = ".potm"
    PPSM = ".ppsm"
    PPTM = ".pptm"

    HTML = ".html"
    HTM = ".htm"
    XHTML = ".xhtml"

    XML = ".xml"
    XML_JATS = ".nxml"
    XML_XBRL = ".xbrl"

    ADOC = ".adoc"
    ASCIIDOC = ".asciidoc"
    ASC = ".asc"

    METS_GBS = ".tar.gz"

    LATEX = ".tex"
    LATEX_ALT = ".latex"

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
    XLSM = ".xlsm"

    # Audio formats
    AUDIO_WAV = ".wav"
    AUDIO_MP3 = ".mp3"
    AUDIO_M4A = ".m4a"
    AUDIO_AAC = ".aac"
    AUDIO_OGG = ".ogg"
    AUDIO_FLAC = ".flac"
    VIDEO_MP4 = ".mp4"
    VIDEO_AVI = ".avi"
    VIDEO_MOV = ".mov"


def get_content_type_enum(content_type_str: str) -> ContentType:
    """Convert a content type string to ContentType enum."""
    return ContentType(content_type_str)


class KnowledgeFilter(BaseModel):
    key: str
    value: Any
