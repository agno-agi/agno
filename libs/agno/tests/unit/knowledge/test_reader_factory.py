import pytest

from agno.knowledge.reader.reader_factory import ReaderFactory


@pytest.mark.parametrize(
    ("content_type", "expected_reader"),
    [
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"),
        ("application/msword", "docx"),
        ("application/json", "json"),
        ("application/json; charset=utf-8", "json"),
        ("text/markdown", "markdown"),
        ("text/plain; charset=UTF-8", "text"),
    ],
)
def test_get_reader_for_extension_routes_mime_types(monkeypatch, content_type, expected_reader):
    monkeypatch.setattr(ReaderFactory, "create_reader", lambda reader_key: reader_key)

    assert ReaderFactory.get_reader_for_extension(content_type) == expected_reader
