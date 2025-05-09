# Common file formatting utility for embedding files into chat messages
import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union
from urllib.parse import urlparse

from agno.media import File
from agno.utils.log import log_debug, log_error


# Add a utility to normalize various file inputs into File objects
def normalize_files(files: Sequence[Union[File, Path, str]]) -> List[File]:
    """
    Convert a sequence of File, Path, or URL/filepath strings to a list of File objects.
    """
    from pathlib import Path as _Path

    normalized: List[File] = []
    for f in files:
        if isinstance(f, File):
            normalized.append(f)
        elif isinstance(f, _Path):
            normalized.append(File(filepath=f))
        elif isinstance(f, str):
            if f.startswith("http://") or f.startswith("https://"):
                normalized.append(File(url=f))
            else:
                normalized.append(File(filepath=_Path(f)))
        else:
            raise ValueError(f"Unsupported file type: {f!r}")
    return normalized


def _get_mime_type(file: File, filename: str) -> str:
    """Determine MIME type from File object or filename."""
    return file.mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _format_file_inline(file: File) -> Optional[Dict[str, Any]]:
    """
    Inline-embed a file as a base64 data URL.
    Supports URL, local filepath, and raw content.
    """
    try:
        # Determine content source
        print(f"oFrmatting file inline: {file.filepath or file.url}")
        if file.url:
            result = file.file_url_content
            if result is None:
                log_error(f"Failed to fetch file from URL: {file.url}")
                return None
            # result is a tuple (bytes, mime_type)
            content, mime_type = result
            # Log first 100 bytes of content
            log_debug(f"File URL content (first 100 bytes): {content[:100]!r}")  # type: ignore[index]
            filename = Path(urlparse(file.url).path).name or "file"
        elif file.filepath:
            path = Path(file.filepath)
            if not path.is_file():
                log_error(f"File not found: {path}")
                return None
            content = path.read_bytes()
            filename = path.name
            mime_type = _get_mime_type(file, filename)
        elif file.content is not None:
            # Ensure bytes
            if isinstance(file.content, bytes):
                content = file.content
            else:
                content = str(file.content).encode("utf-8")
            filename = getattr(file, "filename", "file")
            mime_type = _get_mime_type(file, filename)
        else:
            return None

        # Encode to base64 data URL
        encoded = base64.b64encode(content).decode("utf-8")
        data_url = f"data:{mime_type};base64,{encoded}"
        return {"type": "file", "file": {"filename": filename, "file_data": data_url}}
    except Exception as e:
        log_error(f"Error formatting file inline: {e}")
        return None


def _process_with_reader(file: File) -> Optional[list[dict[str, str]]]:
    if file.url and str(file.url).lower().endswith(".json"):
        try:
            import json

            import httpx

            response = httpx.get(file.url)
            parsed = response.json()
            text = json.dumps(parsed, indent=2)
            return [{"type": "text", "text": text}]
        except Exception as e:
            log_error(f"Error fetching or parsing JSON from URL {file.url}: {e}")
            return None
    if not getattr(file, "reader", None):
        return None

    reader_cls = file.reader.__class__.__name__
    log_debug(f"Using reader {reader_cls} on {file.filepath or file.url}")
    try:
        # Determine source: filepath or URL
        source = file.filepath if getattr(file, "filepath", None) else file.url  # type: ignore
        docs = file.reader.read(source)  # type: ignore
        content_parts = []
        for doc in reversed(docs):
            snippet = (doc.content or "").strip().replace("\n", " ")[:10]
            log_debug(f"Reader {reader_cls} produced doc id={doc.id}, snippet='{snippet}...'")
            content_parts.append({"type": "text", "text": doc.content or ""})
        return content_parts
    except Exception as e:
        log_error(f"Error reading with {reader_cls}: {e}")
        return None


def _auto_detect_reader(file: File) -> None:
    """Auto-detect and apply appropriate reader based on file type."""
    if getattr(file, "reader", None) is None and (getattr(file, "filepath", None) or getattr(file, "url", None)):
        # Use filepath or URL to detect reader
        path_lower = str(file.filepath or file.url).lower()
        if path_lower.endswith(".pdf"):
            try:
                # Use URL reader for PDF URLs, else local PDF reader
                if getattr(file, "url", None):
                    from agno.document.reader.pdf_reader import PDFUrlReader

                    file.reader = PDFUrlReader()
                    log_debug(f"Auto-applied PDFUrlReader for {file.url}")
                else:
                    from agno.document.reader.pdf_reader import PDFReader

                    file.reader = PDFReader()
                    log_debug(f"Auto-applied PDFReader for {file.filepath}")
            except ImportError as e:
                log_error(f"Failed to import PDF reader for {file.filepath or file.url}: {e}")
        elif path_lower.endswith(".csv"):
            try:
                from agno.document.reader.csv_reader import CSVReader

                file.reader = CSVReader()
                log_debug(f"Auto-applied CSVReader for {file.filepath}")
            except ImportError as e:
                log_error(f"Failed to import CSVReader for {file.filepath}: {e}")
        elif path_lower.endswith(".docx"):
            try:
                from agno.document.reader.docx_reader import DocxReader

                file.reader = DocxReader()
                log_debug(f"Auto-applied DocxReader for {file.filepath}")
            except ImportError as e:
                log_error(f"Failed to import DocxReader for {file.filepath}: {e}")
        elif path_lower.endswith(".json"):
            try:
                from agno.document.reader.json_reader import JSONReader

                file.reader = JSONReader()
                log_debug(f"Auto-applied JSONReader for {file.filepath}")
            except ImportError as e:
                log_error(f"Failed to import JSONReader for {file.filepath}: {e}")
        elif path_lower.endswith((".txt", ".md")):
            try:
                from agno.document.reader.text_reader import TextReader

                file.reader = TextReader()
                log_debug(f"Auto-applied TextReader for {file.filepath}")
            except ImportError as e:
                log_error(f"Failed to import TextReader for {file.filepath}: {e}")


def prepare_inline_files(files: Sequence[File]) -> List[Dict[str, Any]]:
    """
    For a sequence of File objects, attempt text extraction via reader,
    falling back to Base64 inline embedding. Returns list of message items:
    either {'type':'text','text':...} or the raw inline dict from _format_file_inline.
    """
    items: List[Dict[str, Any]] = []
    for file in files:
        # Case 1: User provided a reader
        parts = _process_with_reader(file)
        if not parts:
            log_debug(f"No parts found for {file.filepath or file.url}")
            # Case 2: Auto-detect reader
            _auto_detect_reader(file)
            parts = _process_with_reader(file)
        if parts:
            # parts are dicts like {'type':'text','text':...}
            items.extend(parts)
            continue
        # Case 3: Embed file as base64 data URL
        log_debug(f"Falling back to inline embedding for {file.filepath or file.url}")
        inline = _format_file_inline(file)
        if inline:
            # inline is a dict like {'type':'file','file':{...}}
            items.append(inline)
    return items
