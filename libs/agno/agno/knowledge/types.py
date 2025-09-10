from enum import Enum


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
    JSON = ".json"

    # Spreadsheet file extensions
    CSV = ".csv"
    XLSX = ".xlsx"
    XLS = ".xls"


def get_content_type_enum(content_type_str: str) -> ContentType:
    """Convert a content type string to ContentType enum."""
    return ContentType(content_type_str)
