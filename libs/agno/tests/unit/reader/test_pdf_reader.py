import asyncio
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from agno.document.reader.pdf_reader import (
    PDFImageReader,
    PDFReader,
    PDFUrlImageReader,
    PDFUrlReader,
)


@pytest.fixture(scope="session")
def sample_pdf_path(tmp_path_factory) -> Path:
    # Use tmp_path_factory for session-scoped temporary directory
    tmp_path = tmp_path_factory.mktemp("pdf_tests")
    pdf_path = tmp_path / "ThaiRecipes.pdf"

    # Only download if file doesn't exist
    if not pdf_path.exists():
        url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

        # Download the PDF file
        response = httpx.get(url)
        response.raise_for_status()

        # Save to temporary location
        pdf_path.write_bytes(response.content)

    return pdf_path


@pytest.fixture(scope="session")
def sample_pdf_url() -> str:
    return "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"


def test_pdf_reader_read_file(sample_pdf_path):
    reader = PDFReader()
    documents = reader.read(sample_pdf_path)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)
    assert all(isinstance(doc.meta_data.get("page"), int) for doc in documents)


@pytest.mark.asyncio
async def test_pdf_reader_async_read_file(sample_pdf_path):
    reader = PDFReader()
    documents = await reader.async_read(sample_pdf_path)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)
    assert all(isinstance(doc.meta_data.get("page"), int) for doc in documents)


def test_pdf_reader_with_chunking(sample_pdf_path):
    reader = PDFReader()
    reader.chunk = True
    documents = reader.read(sample_pdf_path)

    assert len(documents) > 0
    assert all("chunk" in doc.meta_data for doc in documents)


def test_pdf_url_reader(sample_pdf_url):
    reader = PDFUrlReader()
    documents = reader.read(sample_pdf_url)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)


@pytest.mark.asyncio
async def test_pdf_url_reader_async(sample_pdf_url):
    reader = PDFUrlReader()
    documents = await reader.async_read(sample_pdf_url)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)


def test_pdf_image_reader(sample_pdf_path):
    reader = PDFImageReader()
    documents = reader.read(sample_pdf_path)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)


@pytest.mark.asyncio
async def test_pdf_image_reader_async(sample_pdf_path):
    reader = PDFImageReader()
    documents = await reader.async_read(sample_pdf_path)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)


def test_pdf_url_image_reader(sample_pdf_url):
    reader = PDFUrlImageReader()
    documents = reader.read(sample_pdf_url)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)


@pytest.mark.asyncio
async def test_pdf_url_image_reader_async(sample_pdf_url):
    reader = PDFUrlImageReader()
    documents = await reader.async_read(sample_pdf_url)

    assert len(documents) > 0
    assert all(doc.name == "ThaiRecipes" for doc in documents)
    assert all(doc.content for doc in documents)


def test_pdf_reader_invalid_file():
    reader = PDFReader()
    with pytest.raises(Exception):
        reader.read("nonexistent.pdf")


def test_pdf_url_reader_invalid_url():
    reader = PDFUrlReader()
    with pytest.raises(ValueError):
        reader.read("")


@pytest.mark.asyncio
async def test_async_pdf_processing(sample_pdf_path):
    reader = PDFReader()
    tasks = [reader.async_read(sample_pdf_path) for _ in range(3)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 3
    assert all(len(docs) > 0 for docs in results)
    assert all(all(doc.name == "ThaiRecipes" for doc in docs) for docs in results)


def test_pdf_reader_empty_pdf():
    empty_pdf = BytesIO(b"%PDF-1.4")
    empty_pdf.name = "empty.pdf"

    reader = PDFReader()
    documents = reader.read(empty_pdf)

    assert len(documents) == 0
