import asyncio
from io import BytesIO

import pytest
from docx import Document as DocxDocument

from agno.knowledge.reader.docx_reader import DocxReader


@pytest.fixture
def docx_file(tmp_path):
    document = DocxDocument()
    document.add_paragraph("First paragraph")
    document.add_paragraph("Second paragraph")
    path = tmp_path / "test.docx"
    document.save(path)
    return path


@pytest.fixture(
    params=[("read", "path"), ("read", "bytesio"), ("async_read", "path"), ("async_read", "bytesio")],
    ids=["sync-path", "sync-bytesio", "async-path", "async-bytesio"],
)
def read_docx(request, tmp_path):
    """Save a real DOCX and exercise each reader method and input type."""
    method, file_type = request.param

    async def read(document, **kwargs):
        source = tmp_path / "tables.docx" if file_type == "path" else BytesIO()
        document.save(source)
        if isinstance(source, BytesIO):
            source.seek(0)
        reader = DocxReader(**{"chunk": False, **kwargs})
        if method == "async_read":
            return await reader.async_read(source)
        return reader.read(source)

    return read


def test_docx_reader_read_file(docx_file):
    documents = DocxReader().read(docx_file)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content == "First paragraph\n\nSecond paragraph"


@pytest.mark.asyncio
async def test_docx_reader_async_read_file(docx_file):
    documents = await DocxReader().async_read(docx_file)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content == "First paragraph\n\nSecond paragraph"


def test_docx_reader_with_chunking(docx_file):
    documents = DocxReader(chunk_size=20).read(docx_file)

    assert [document.content for document in documents] == ["First paragraph", "Second paragraph"]
    assert [document.meta_data["chunk"] for document in documents] == [1, 2]
    assert all(document.name == "test" for document in documents)


def test_docx_reader_bytesio(docx_file):
    file_obj = BytesIO(docx_file.read_bytes())
    file_obj.name = "test.docx"

    documents = DocxReader().read(file_obj)

    assert len(documents) == 1
    assert documents[0].name == "test"
    assert documents[0].content == "First paragraph\n\nSecond paragraph"


def test_docx_reader_invalid_file(tmp_path):
    assert DocxReader().read(tmp_path / "nonexistent.docx") == []


def test_docx_reader_file_error():
    assert DocxReader().read(BytesIO(b"not a DOCX package")) == []


@pytest.mark.asyncio
async def test_async_docx_processing(docx_file):
    reader = DocxReader()
    results = await asyncio.gather(*(reader.async_read(docx_file) for _ in range(3)))

    assert len(results) == 3
    assert all(len(documents) == 1 for documents in results)
    assert all(documents[0].name == "test" for documents in results)
    assert all(documents[0].content == "First paragraph\n\nSecond paragraph" for documents in results)


@pytest.mark.asyncio
async def test_docx_reader_async_with_chunking(docx_file):
    documents = await DocxReader(chunk_size=20).async_read(docx_file)

    assert [document.content for document in documents] == ["First paragraph", "Second paragraph"]
    assert [document.meta_data["chunk"] for document in documents] == [1, 2]
    assert all(document.name == "test" for document in documents)


def test_docx_reader_metadata(docx_file):
    documents = DocxReader().read(docx_file, name="Custom document")

    assert len(documents) == 1
    assert documents[0].name == "Custom document"
    assert documents[0].content == "First paragraph\n\nSecond paragraph"


def test_docx_reader_chunk_size_propagation():
    from agno.knowledge.chunking.document import DocumentChunking

    reader = DocxReader(chunk_size=350)
    assert reader.chunk_size == 350
    assert reader.chunking_strategy.chunk_size == 350
    assert isinstance(reader.chunking_strategy, DocumentChunking)


def test_docx_reader_default_chunk_size():
    from agno.knowledge.chunking.document import DocumentChunking

    reader = DocxReader()
    assert reader.chunk_size == 5000
    assert reader.chunking_strategy.chunk_size == 5000
    assert isinstance(reader.chunking_strategy, DocumentChunking)


@pytest.mark.asyncio
async def test_docx_reader_table_only(read_docx):
    document = DocxDocument()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Item"
    table.cell(0, 1).text = "Quantity"
    table.cell(1, 0).text = "Apples"
    table.cell(1, 1).text = "12"

    documents = await read_docx(document)

    assert len(documents) == 1
    assert documents[0].content == "Item\tQuantity\nApples\t12"


@pytest.mark.asyncio
async def test_docx_reader_preserves_paragraph_and_table_order(read_docx):
    document = DocxDocument()
    document.add_paragraph("Before")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "First table"
    document.add_paragraph("Between")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Second table"
    document.add_paragraph("After")

    documents = await read_docx(document)

    assert documents[0].content == "Before\n\nFirst table\n\nBetween\n\nSecond table\n\nAfter"


@pytest.mark.asyncio
async def test_docx_reader_horizontal_merged_cells(read_docx):
    document = DocxDocument()
    table = document.add_table(rows=2, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "Merged heading"
    table.cell(0, 2).text = "Other heading"
    table.cell(1, 0).text = "Repeated"
    table.cell(1, 1).text = "Repeated"
    table.cell(1, 2).text = "Last"

    documents = await read_docx(document)

    assert documents[0].content == "Merged heading\tOther heading\nRepeated\tRepeated\tLast"


@pytest.mark.asyncio
async def test_docx_reader_vertical_merged_cells(read_docx):
    document = DocxDocument()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(1, 0)).text = "Merged label"
    table.cell(0, 1).text = "First value"
    table.cell(1, 1).text = "Second value"

    documents = await read_docx(document)

    assert documents[0].content == "Merged label\tFirst value\nSecond value"


@pytest.mark.asyncio
async def test_docx_reader_nested_table(read_docx):
    document = DocxDocument()
    document.add_paragraph("Document before")
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.paragraphs[0].text = "Cell before"
    nested_table = cell.add_table(rows=1, cols=2)
    nested_table.cell(0, 0).text = "Nested left"
    nested_table.cell(0, 1).text = "Nested right"
    cell.paragraphs[-1].text = "Cell after"
    document.add_paragraph("Document after")

    documents = await read_docx(document)

    assert documents[0].content == (
        "Document before\n\nCell before\nNested left\tNested right\nCell after\n\nDocument after"
    )


@pytest.mark.asyncio
async def test_docx_reader_preserves_paragraph_whitespace(read_docx):
    document = DocxDocument()
    document.add_paragraph("  First\tline\nSecond line  ")
    document.add_paragraph("")
    document.add_paragraph("Last")

    documents = await read_docx(document)

    assert documents[0].content == "  First\tline\nSecond line  \n\n\n\nLast"


@pytest.mark.asyncio
async def test_docx_reader_chunks_table_content(read_docx):
    document = DocxDocument()
    document.add_paragraph("Before")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Inside"
    document.add_paragraph("After")

    documents = await read_docx(document, chunk=True, chunk_size=6)

    assert [document.content for document in documents] == ["Before", "Inside", "After"]
    assert [document.meta_data["chunk"] for document in documents] == [1, 2, 3]
