import asyncio
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from agno.knowledge.reader.pdf_reader import (
    PDFImageReader,
    PDFReader,
    _clean_page_numbers,
    _sanitize_pdf_text,
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
    assert all("ThaiRecipes" in doc.name for doc in documents)
    assert all(doc.content for doc in documents)
    assert all(isinstance(doc.meta_data.get("page"), int) for doc in documents)


@pytest.mark.asyncio
async def test_pdf_reader_async_read_file(sample_pdf_path):
    reader = PDFReader()
    documents = await reader.async_read(sample_pdf_path)

    assert len(documents) > 0
    assert all("ThaiRecipes" in doc.name for doc in documents)
    assert all(doc.content for doc in documents)
    assert all(isinstance(doc.meta_data.get("page"), int) for doc in documents)


def test_pdf_reader_with_chunking(sample_pdf_path):
    from agno.knowledge.chunking.document import DocumentChunking

    reader = PDFReader(chunking_strategy=DocumentChunking(chunk_size=50))
    reader.chunk = True
    documents = reader.read(sample_pdf_path)

    assert len(documents) > 0
    assert all("chunk" in doc.meta_data for doc in documents)


def test_pdf_reader_with_chunking_and_pages_merged(sample_pdf_path):
    reader = PDFReader(split_on_pages=False, chunk=True, chunk_size=5000)
    documents_unsplit = reader.read(sample_pdf_path)

    assert len(documents_unsplit) > 0
    assert all("chunk" in doc.meta_data for doc in documents_unsplit)

    # Chunking per page is different then chunking the whole document
    reader = PDFReader(split_on_pages=True, chunk=True, chunk_size=5000)
    documents_splitted = reader.read(sample_pdf_path)

    assert len(documents_splitted) > len(documents_unsplit)


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


def test_pdf_reader_invalid_file():
    reader = PDFReader()
    with pytest.raises(Exception):
        reader.read("nonexistent.pdf")


@pytest.mark.asyncio
async def test_async_pdf_processing(sample_pdf_path):
    reader = PDFReader()
    tasks = [reader.async_read(sample_pdf_path) for _ in range(3)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 3
    assert all(len(docs) > 0 for docs in results)
    assert all(all("ThaiRecipes" in doc.name for doc in docs) for docs in results)
    assert all(all("page" in doc.meta_data for doc in docs) for docs in results)


@pytest.mark.asyncio
async def test_async_pdf_processing_with_pages_merged(sample_pdf_path):
    reader = PDFReader(split_on_pages=False, chunk=False)
    tasks = [reader.async_read(sample_pdf_path) for _ in range(3)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 3
    assert all(len(docs) == 1 for docs in results)
    assert all(all("ThaiRecipes" == doc.name for doc in docs) for docs in results)
    assert all(all("page" not in doc.meta_data for doc in docs) for docs in results)


def test_pdf_reader_empty_pdf():
    empty_pdf = BytesIO(b"%PDF-1.4")
    empty_pdf.name = "empty.pdf"

    reader = PDFReader()
    documents = reader.read(empty_pdf)

    assert len(documents) == 0


@pytest.fixture
def valid_page_numbers():
    return [list(range(strt, 10 + strt)) for strt in (-2, -1, 0, 1, 2)]


@pytest.fixture
def invalid_page_numbers():
    return [list(range(strt, 10 + strt)) for strt in (-4, -3, 3, 60, 99)]


@pytest.fixture
def p_nr_format():
    return {"start": "<start page {page_nr}>", "end": "<end page {page_nr}>"}


@pytest.mark.parametrize("shift_index", [0, 1, 2, 3, 4])
def test_clean_start_page_numbers_valid(valid_page_numbers, p_nr_format, shift_index):
    x = valid_page_numbers[shift_index]
    shift = x[0]

    content = [
        f"{x[0]}page one",
        f"  {x[1]}3 page two",
        "",
        f"{x[3]} another page",
        f"{x[4]}another page",
    ]

    clean_content, recognized_shift = _clean_page_numbers(
        content,
        page_start_numbering_format=p_nr_format["start"],
        page_end_numbering_format=p_nr_format["end"],
    )

    assert shift == recognized_shift
    assert clean_content[0].startswith(p_nr_format["start"].format(page_nr=shift))
    assert clean_content[0].endswith(p_nr_format["end"].format(page_nr=shift))


@pytest.mark.parametrize("shift_index", [0, 1, 2, 3, 4])
def test_clean_start_page_numbers_invalid(invalid_page_numbers, p_nr_format, shift_index):
    x = invalid_page_numbers[shift_index]
    shift = x[0]

    content = [
        f"{x[0]}page one",
        f"  {x[1]}3 page two",
        "",
        f"{x[3]} another page",
        f"{x[4]}another page",
    ]

    clean_content, recognized_shift = _clean_page_numbers(
        content,
        page_start_numbering_format=p_nr_format["start"],
        page_end_numbering_format=p_nr_format["end"],
    )

    assert recognized_shift is None
    assert not clean_content[0].startswith(p_nr_format["start"].format(page_nr=shift))
    assert not clean_content[0].endswith(p_nr_format["end"].format(page_nr=shift))


@pytest.mark.parametrize("shift_index", [0, 1, 2, 3, 4])
def test_clean_end_page_numbers_valid(valid_page_numbers, p_nr_format, shift_index):
    x = valid_page_numbers[shift_index]
    shift = x[0]

    content = [
        f"page one{x[0]}",
        f" page two 3{x[1]} ",
        "",
        f"another page {x[3]}",
        f"another page{x[4]}",
    ]

    clean_content, recognized_shift = _clean_page_numbers(
        content,
        page_start_numbering_format=p_nr_format["start"],
        page_end_numbering_format=p_nr_format["end"],
    )

    assert shift == recognized_shift
    assert clean_content[0].startswith(p_nr_format["start"].format(page_nr=shift))
    assert clean_content[0].endswith(p_nr_format["end"].format(page_nr=shift))


@pytest.mark.parametrize("shift_index", [0, 1, 2, 3, 4])
def test_clean_end_page_numbers_invalid(invalid_page_numbers, p_nr_format, shift_index):
    x = invalid_page_numbers[shift_index]
    shift = x[0]

    content = [
        f"page one{x[0]}",
        f" page two 3{x[1]} ",
        "",
        f"another page {x[3]}",
        f"another page{x[4]}",
    ]

    clean_content, recognized_shift = _clean_page_numbers(
        content,
        page_start_numbering_format=p_nr_format["start"],
        page_end_numbering_format=p_nr_format["end"],
    )

    assert recognized_shift is None
    assert not clean_content[0].startswith(p_nr_format["start"].format(page_nr=shift))
    assert not clean_content[0].endswith(p_nr_format["end"].format(page_nr=shift))


@pytest.mark.parametrize("shift_index", [0, 1, 2, 3, 4])
def test_clean_start_end_page_numbers_valid(valid_page_numbers, p_nr_format, shift_index):
    x = valid_page_numbers[shift_index]
    shift = x[0]

    content = [
        f"page one{x[0]}",
        f" {x[1]}page two 3 ",
        "",
        f"another page {x[3]}",
        f"{x[4]}another page",
    ]

    clean_content, recognized_shift = _clean_page_numbers(
        content,
        page_start_numbering_format=p_nr_format["start"],
        page_end_numbering_format=p_nr_format["end"],
    )

    assert shift == recognized_shift
    assert clean_content[0].startswith(p_nr_format["start"].format(page_nr=shift))
    assert clean_content[0].endswith(p_nr_format["end"].format(page_nr=shift))


def test_clean_page_numbers_untrustable(p_nr_format):
    content = [
        "1page one",
        "  3 guards in front of the door and",
        "there are 4",
        "people in the ",
        "5 rooms",
        ".",
    ]

    clean_content, recognized_shift = _clean_page_numbers(
        content,
        page_start_numbering_format=p_nr_format["start"],
        page_end_numbering_format=p_nr_format["end"],
    )

    assert recognized_shift is None
    assert not clean_content[0].startswith(p_nr_format["start"].format(page_nr=1))
    assert not clean_content[0].endswith(p_nr_format["end"].format(page_nr=1))
    assert not clean_content[0].startswith(p_nr_format["start"].format(page_nr=2))
    assert not clean_content[0].endswith(p_nr_format["end"].format(page_nr=2))


def _create_encrypted_pdf_with_empty_password() -> BytesIO:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt(user_password="", owner_password="owner123")

    buffer = BytesIO()
    writer.write(buffer)
    buffer.seek(0)
    buffer.name = "encrypted_empty_password.pdf"
    return buffer


def _create_encrypted_pdf_with_password(password: str) -> BytesIO:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt(user_password=password, owner_password="owner123")

    buffer = BytesIO()
    writer.write(buffer)
    buffer.seek(0)
    buffer.name = "encrypted.pdf"
    return buffer


def test_pdf_reader_decrypt_with_empty_password():
    pdf = _create_encrypted_pdf_with_empty_password()

    reader = PDFReader()
    docs = reader.read(pdf, password="")
    assert docs is not None
    assert len(docs) >= 0


def test_pdf_reader_password_none_falls_back_to_instance():
    pdf = _create_encrypted_pdf_with_empty_password()

    reader = PDFReader(password="")
    docs = reader.read(pdf, password=None)
    assert docs is not None


def test_pdf_reader_explicit_password_overrides_instance():
    pdf = _create_encrypted_pdf_with_empty_password()

    reader = PDFReader(password="wrong")
    docs = reader.read(pdf, password="")
    assert docs is not None


def test_pdf_reader_no_password_for_encrypted_pdf_returns_empty():
    pdf = _create_encrypted_pdf_with_password("secret123")

    reader = PDFReader()
    docs = reader.read(pdf)
    assert docs == []


@pytest.mark.asyncio
async def test_pdf_reader_async_decrypt_with_empty_password():
    pdf = _create_encrypted_pdf_with_empty_password()

    reader = PDFReader()
    docs = await reader.async_read(pdf, password="")
    assert docs is not None


@pytest.mark.asyncio
async def test_pdf_reader_async_password_none_falls_back_to_instance():
    pdf = _create_encrypted_pdf_with_empty_password()

    reader = PDFReader(password="")
    docs = await reader.async_read(pdf, password=None)
    assert docs is not None


def test_sanitize_pdf_text_collapses_newlines():
    text = "dietary\n \nmodifications.\n \nRecommendations\n \nshould\n \nfocus"
    result = _sanitize_pdf_text(text)
    assert result == "dietary modifications. Recommendations should focus"


def test_sanitize_pdf_text_collapses_mixed_whitespace():
    text = "hello\t\n  \n\tworld\n\nfoo   bar"
    result = _sanitize_pdf_text(text)
    # Paragraph break (\n\n) is preserved; word-per-line artifacts (\n \n) are collapsed
    assert result == "hello world\n\nfoo bar"


def test_sanitize_pdf_text_preserves_paragraph_breaks():
    text = "First paragraph ends here.\n\nSecond paragraph starts here."
    result = _sanitize_pdf_text(text)
    assert result == "First paragraph ends here.\n\nSecond paragraph starts here."


def test_sanitize_pdf_text_joins_single_newlines():
    text = "line one\nline two\nline three"
    result = _sanitize_pdf_text(text)
    assert result == "line one line two line three"


def test_sanitize_pdf_text_strips_leading_trailing():
    text = "  \n hello world \n  "
    result = _sanitize_pdf_text(text)
    assert result == "hello world"


def test_sanitize_pdf_text_preserves_clean_text():
    text = "already clean text here"
    result = _sanitize_pdf_text(text)
    assert result == "already clean text here"


def test_sanitize_pdf_text_empty_string():
    assert _sanitize_pdf_text("") == ""
    assert _sanitize_pdf_text("   \n\n  ") == ""


def test_pdf_reader_sanitize_content_enabled_by_default(sample_pdf_path):
    reader = PDFReader()
    assert reader.sanitize_content is True
    documents = reader.read(sample_pdf_path)

    assert len(documents) > 0
    for doc in documents:
        # Sanitized content should not contain sequences of newlines with spaces
        assert "\n \n" not in doc.content


def test_pdf_reader_sanitize_content_disabled(sample_pdf_path):
    reader = PDFReader(sanitize_content=False)
    assert reader.sanitize_content is False
    documents = reader.read(sample_pdf_path)

    assert len(documents) > 0


@pytest.mark.asyncio
async def test_pdf_reader_async_sanitize_content_enabled(sample_pdf_path):
    reader = PDFReader()
    documents = await reader.async_read(sample_pdf_path)

    assert len(documents) > 0
    for doc in documents:
        assert "\n \n" not in doc.content


@pytest.mark.asyncio
async def test_pdf_reader_async_sanitize_content_disabled(sample_pdf_path):
    reader = PDFReader(sanitize_content=False)
    documents = await reader.async_read(sample_pdf_path)

    assert len(documents) > 0
