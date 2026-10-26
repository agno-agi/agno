import io

import pytest

from agno.knowledge.reader.csv_reader import CSVReader
from agno.knowledge.reader.field_labeled_csv_reader import FieldLabeledCSVReader


@pytest.mark.asyncio
@pytest.mark.parametrize("reader_class", [CSVReader, FieldLabeledCSVReader])
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("source", ["path", "bytes", "text"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
@pytest.mark.parametrize("row_count", [1, 12], ids=["small", "paginated"])
async def test_csv_line_endings(tmp_path, reader_class, use_async, source, newline, row_count):
    # Quoted multiline cells must remain one field, even with CR record endings.
    content = newline.join(["name,notes"] + [f'Person {i},"first{newline}second"' for i in range(row_count)])
    content += newline
    if source == "path":
        file = tmp_path / "contacts.csv"
        file.write_bytes(content.encode("utf-8"))
    elif source == "bytes":
        file = io.BytesIO(content.encode("utf-8"))
    else:
        file = io.StringIO(content)

    reader = CSVReader(chunk=False) if reader_class is CSVReader else FieldLabeledCSVReader()
    if use_async:
        documents = await reader.async_read(file, name="contacts", page_size=5)
    else:
        documents = reader.read(file, name="contacts")

    if reader_class is CSVReader:
        expected = ["name, notes"] + [f"Person {i}, first second" for i in range(row_count)]
        assert "\n".join(document.content for document in documents) == "\n".join(expected)
    else:
        assert [document.content for document in documents] == [
            f"Name: Person {i}\nNotes: first second" for i in range(row_count)
        ]
        assert [document.meta_data["row_index"] for document in documents] == list(range(row_count))

    assert all(document.name == "contacts" for document in documents)
    if source != "path":
        assert not file.closed
