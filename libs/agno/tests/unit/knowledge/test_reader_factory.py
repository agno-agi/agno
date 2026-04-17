"""Unit tests for ReaderFactory.get_reader_for_extension() input normalization.

These tests verify the routing logic (which reader key is selected) without
instantiating readers that require optional dependencies (pypdf, aiofiles, etc.).
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.reader.reader_factory import ReaderFactory


@pytest.fixture(autouse=True)
def mock_create_reader():
    """Patch create_reader so no optional dependencies are needed."""
    with patch.object(ReaderFactory, "create_reader", return_value=MagicMock()) as mock:
        yield mock


def _routed_key(ext: str, mock) -> str:
    """Call get_reader_for_extension and return the reader key that was passed to create_reader."""
    ReaderFactory.get_reader_for_extension(ext)
    return mock.call_args[0][0]


# ---------------------------------------------------------------------------
# Dotted extensions — existing behaviour must not regress
# ---------------------------------------------------------------------------


def test_dotted_pdf(mock_create_reader):
    assert _routed_key(".pdf", mock_create_reader) == "pdf"


def test_dotted_csv(mock_create_reader):
    assert _routed_key(".csv", mock_create_reader) == "csv"


def test_dotted_xlsx(mock_create_reader):
    assert _routed_key(".xlsx", mock_create_reader) == "excel"


def test_dotted_xls(mock_create_reader):
    assert _routed_key(".xls", mock_create_reader) == "excel"


def test_dotted_docx(mock_create_reader):
    assert _routed_key(".docx", mock_create_reader) == "docx"


def test_dotted_pptx(mock_create_reader):
    assert _routed_key(".pptx", mock_create_reader) == "pptx"


def test_dotted_json(mock_create_reader):
    assert _routed_key(".json", mock_create_reader) == "json"


def test_dotted_md(mock_create_reader):
    assert _routed_key(".md", mock_create_reader) == "markdown"


def test_dotted_txt(mock_create_reader):
    assert _routed_key(".txt", mock_create_reader) == "text"


# ---------------------------------------------------------------------------
# Bare extensions — previously broken (no leading dot)
# ---------------------------------------------------------------------------


def test_bare_pdf(mock_create_reader):
    assert _routed_key("pdf", mock_create_reader) == "pdf"


def test_bare_csv(mock_create_reader):
    assert _routed_key("csv", mock_create_reader) == "csv"


def test_bare_docx(mock_create_reader):
    assert _routed_key("docx", mock_create_reader) == "docx"


def test_bare_json(mock_create_reader):
    assert _routed_key("json", mock_create_reader) == "json"


def test_bare_md(mock_create_reader):
    assert _routed_key("md", mock_create_reader) == "markdown"


# ---------------------------------------------------------------------------
# MIME types without params — existing behaviour must not regress
# ---------------------------------------------------------------------------


def test_mime_pdf(mock_create_reader):
    assert _routed_key("application/pdf", mock_create_reader) == "pdf"


def test_mime_csv(mock_create_reader):
    assert _routed_key("text/csv", mock_create_reader) == "csv"


def test_mime_docx(mock_create_reader):
    key = _routed_key(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        mock_create_reader,
    )
    assert key == "docx"


def test_mime_xlsx(mock_create_reader):
    key = _routed_key(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        mock_create_reader,
    )
    assert key == "excel"


# ---------------------------------------------------------------------------
# MIME types with charset params — previously broken
# ---------------------------------------------------------------------------


def test_mime_csv_with_charset(mock_create_reader):
    assert _routed_key("text/csv; charset=UTF-8", mock_create_reader) == "csv"


def test_mime_pdf_with_charset(mock_create_reader):
    assert _routed_key("application/pdf; charset=utf-8", mock_create_reader) == "pdf"


def test_mime_plain_with_charset(mock_create_reader):
    assert _routed_key("text/plain; charset=utf-8", mock_create_reader) == "text"


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------


def test_uppercase_extension(mock_create_reader):
    assert _routed_key("PDF", mock_create_reader) == "pdf"


def test_mixed_case_dotted(mock_create_reader):
    assert _routed_key(".Pdf", mock_create_reader) == "pdf"


# ---------------------------------------------------------------------------
# Equivalent input forms route to the same reader key
# ---------------------------------------------------------------------------


def test_pdf_all_forms_are_equivalent(mock_create_reader):
    forms = [".pdf", "pdf", "application/pdf", "application/pdf; charset=utf-8", "PDF"]
    keys = {_routed_key(f, mock_create_reader) for f in forms}
    assert keys == {"pdf"}


def test_csv_all_forms_are_equivalent(mock_create_reader):
    forms = [".csv", "csv", "text/csv", "text/csv; charset=UTF-8", "application/csv"]
    keys = {_routed_key(f, mock_create_reader) for f in forms}
    assert keys == {"csv"}


# ---------------------------------------------------------------------------
# Unknown types fall back to text reader
# ---------------------------------------------------------------------------


def test_unknown_extension_fallback(mock_create_reader):
    assert _routed_key("xyz", mock_create_reader) == "text"


def test_unknown_mime_fallback(mock_create_reader):
    assert _routed_key("application/octet-stream", mock_create_reader) == "text"
