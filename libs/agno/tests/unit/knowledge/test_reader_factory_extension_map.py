"""Unit tests for configurable ReaderFactory extension mapping and Knowledge selection."""

from unittest.mock import MagicMock

import pytest

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.docx_reader import DocxReader
from agno.knowledge.reader.reader_factory import ReaderFactory
from agno.knowledge.reader.text_reader import TextReader


@pytest.fixture(autouse=True)
def _reset_reader_factory():
    ReaderFactory.clear_cache()
    ReaderFactory.reset_extension_map()
    yield
    ReaderFactory.clear_cache()
    ReaderFactory.reset_extension_map()


def test_default_extension_mapping():
    assert ReaderFactory.get_reader_key_for_extension(".pdf") == "pdf"
    assert ReaderFactory.get_reader_key_for_extension("application/pdf") == "pdf"
    assert ReaderFactory.get_reader_key_for_extension(".docx") == "docx"
    assert ReaderFactory.get_reader_key_for_extension(".unknown") == "text"


def test_set_reader_key_for_extension():
    ReaderFactory.set_reader_key_for_extension(".pdf", "docling")
    assert ReaderFactory.get_reader_key_for_extension(".pdf") == "docling"
    assert ReaderFactory.get_reader_key_for_extension(".PDF") == "docling"


def test_set_reader_injects_cache():
    custom = DocxReader(preserve_images=True)
    ReaderFactory.set_reader("docx", custom)
    assert ReaderFactory.create_reader("docx") is custom
    assert ReaderFactory.get_reader_for_extension(".docx") is custom


def test_set_reader_replace_false_keeps_existing():
    first = DocxReader(preserve_images=False)
    second = DocxReader(preserve_images=True)
    ReaderFactory.set_reader("docx", first)
    ReaderFactory.set_reader("docx", second, replace=False)
    assert ReaderFactory.create_reader("docx") is first


def test_knowledge_select_reader_uses_instance_readers():
    custom_pdf = MagicMock(name="CustomPdfReader")
    custom_docx = DocxReader(preserve_images=True)
    knowledge = Knowledge(
        readers={
            "pdf": custom_pdf,
            "docx": custom_docx,
        }
    )

    assert knowledge._select_reader(".pdf") is custom_pdf
    assert knowledge._select_reader(".docx") is custom_docx
    reader, name = knowledge._select_reader_by_extension(".pdf")
    assert reader is custom_pdf
    assert name == ""
    assert knowledge._select_reader_by_uri("s3://bucket/docs/file.docx") is custom_docx


def test_knowledge_select_reader_respects_factory_extension_remap():
    custom_docling = MagicMock(name="CustomDoclingReader")
    ReaderFactory.set_reader_key_for_extension(".pdf", "docling")
    knowledge = Knowledge(readers={"docling": custom_docling})

    assert knowledge._select_reader(".pdf") is custom_docling
    assert knowledge._select_reader_by_uri("/tmp/report.PDF") is custom_docling


def test_select_reader_by_extension_csv_default_name():
    knowledge = Knowledge(readers={"csv": TextReader()})
    reader, name = knowledge._select_reader_by_extension(".csv")
    assert reader is knowledge.readers["csv"]
    assert name == "data.csv"
