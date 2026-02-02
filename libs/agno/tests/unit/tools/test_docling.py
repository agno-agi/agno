import json
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("docling")

from agno.tools.docling import DoclingTools


@pytest.fixture
def mock_converter():
    with patch("agno.tools.docling.DocumentConverter") as mock_converter_cls:
        converter_instance = Mock()
        mock_converter_cls.return_value = converter_instance
        yield converter_instance


def _build_mock_result(
    markdown: str = "# Title",
    text: str = "Plain text",
    html: str = "<h1>Title</h1>",
    doctags: str = "<doc>DocTags</doc>",
):
    document = Mock()
    document.export_to_markdown.return_value = markdown
    document.export_to_text.return_value = text
    document.export_to_html.return_value = html
    document.export_to_dict.return_value = {"title": "Docling"}
    document.export_to_doctags.return_value = doctags
    result = Mock()
    result.document = document
    return result


class TestDoclingToolsInitialization:
    def test_initialization_default(self, mock_converter):
        tools = DoclingTools()
        assert tools.name == "docling_tools"
        function_names = [func.name for func in tools.functions.values()]
        assert "convert_to_markdown" in function_names
        assert "convert_to_text" in function_names
        assert "convert_to_html" in function_names
        assert "convert_to_json" in function_names
        assert "convert_to_doctags" in function_names

    def test_initialization_flags(self, mock_converter):
        tools = DoclingTools(
            enable_convert_to_html=False, enable_convert_to_json=False, enable_convert_to_doctags=False
        )
        function_names = [func.name for func in tools.functions.values()]
        assert "convert_to_markdown" in function_names
        assert "convert_to_text" in function_names
        assert "convert_to_html" not in function_names
        assert "convert_to_json" not in function_names
        assert "convert_to_doctags" not in function_names


class TestDoclingToolsConversion:
    def test_convert_to_markdown_success(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.return_value = _build_mock_result(markdown="# Doc")

        result = tools.convert_to_markdown("https://example.com/doc.pdf")

        assert result == "# Doc"
        mock_converter.convert.assert_called_once_with(
            "https://example.com/doc.pdf", headers=None, raises_on_error=True
        )

    def test_convert_to_text_truncation(self, mock_converter):
        tools = DoclingTools(max_chars=5)
        mock_converter.convert.return_value = _build_mock_result(text="123456789")

        result = tools.convert_to_text("/tmp/doc.pdf")

        assert result == "12345..."

    def test_convert_to_html_success(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.return_value = _build_mock_result(html="<p>Ok</p>")

        result = tools.convert_to_html("/tmp/doc.pdf")

        assert result == "<p>Ok</p>"

    def test_convert_to_json_success(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.return_value = _build_mock_result()

        result = tools.convert_to_json("/tmp/doc.pdf")

        assert json.loads(result) == {"title": "Docling"}

    def test_convert_to_doctags_success(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.return_value = _build_mock_result(doctags="<doc>ok</doc>")

        result = tools.convert_to_doctags("/tmp/doc.pdf")

        assert result == "<doc>ok</doc>"

    def test_convert_empty_source(self, mock_converter):
        tools = DoclingTools()
        result = tools.convert_to_markdown("")
        assert result == "Error: No source provided"

    def test_convert_exception(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.side_effect = Exception("boom")

        result = tools.convert_to_markdown("/tmp/doc.pdf")

        assert result == "Error converting document: boom"
