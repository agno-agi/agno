"""
Text Reader Tool
================

Reads text content from text files (.txt, .md, etc.).
"""

from pathlib import Path

from agno.utils.log import logger


# ============================================================================
# Text Reader Tool
# ============================================================================
def read_text_file(file_path: str) -> str:
    """Read content from a text file.

    Supports: .txt, .md, .markdown, .rst, .text

    Args:
        file_path: Path to the text file.

    Returns:
        Content of the text file.
    """
    path = Path(file_path)
    if not path.exists():
        return f"Error: File not found: {file_path}"

    supported_extensions = {".txt", ".md", ".markdown", ".rst", ".text"}
    if path.suffix.lower() not in supported_extensions:
        return f"Error: Unsupported file type: {path.suffix}. Supported: {supported_extensions}"

    try:
        # Try common encodings
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]

        content = None
        for encoding in encodings:
            try:
                content = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            return "Error: Could not decode file with supported encodings"

        logger.info(f"Read text file: {path.name} ({len(content)} chars)")

        # Add metadata
        word_count = len(content.split())
        metadata = f"File: {path.name}\nType: {path.suffix}\nWords: {word_count}"

        return f"{metadata}\n\n{content}"

    except Exception as e:
        logger.error(f"Error reading text file {file_path}: {e}")
        return f"Error reading file: {e}"
