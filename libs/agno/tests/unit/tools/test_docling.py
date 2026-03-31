import json
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("docling")

from docling.datamodel.base_models import InputFormat

from agno.tools.docling import DoclingTools, PdfFormatOption, PdfPipelineOptions


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
    html_split_page: str = "<div class='page'>Title</div>",
    doctags: str = "<doc>DocTags</doc>",
    vtt: str = "WEBVTT\n\n00:00.000 --> 00:02.000\nHello",
):
    document = Mock()
    document.export_to_markdown.return_value = markdown
    document.export_to_text.return_value = text
    document.export_to_html.side_effect = lambda *args, **kwargs: (
        html_split_page if kwargs.get("split_page_view") else html
    )
    document.export_to_dict.return_value = {"title": "Docling"}
    document.export_to_doctags.return_value = doctags
    document.export_to_vtt.return_value = vtt
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
        assert "convert_to_html_split_page" in function_names
        assert "convert_to_json" in function_names
        assert "convert_to_yaml" in function_names
        assert "convert_to_doctags" in function_names
        assert "convert_to_vtt" in function_names
        assert "convert_string_content" in function_names
        assert "list_supported_parsers" in function_names

    def test_initialization_flags(self, mock_converter):
        tools = DoclingTools(
            enable_convert_to_html=False,
            enable_convert_to_html_split_page=False,
            enable_convert_to_json=False,
            enable_convert_to_yaml=False,
            enable_convert_to_doctags=False,
            enable_convert_to_vtt=False,
            enable_convert_string_content=False,
            enable_list_supported_parsers=False,
        )
        function_names = [func.name for func in tools.functions.values()]
        assert "convert_to_markdown" in function_names
        assert "convert_to_text" in function_names
        assert "convert_to_html" not in function_names
        assert "convert_to_html_split_page" not in function_names
        assert "convert_to_json" not in function_names
        assert "convert_to_yaml" not in function_names
        assert "convert_to_doctags" not in function_names
        assert "convert_to_vtt" not in function_names
        assert "convert_string_content" not in function_names
        assert "list_supported_parsers" not in function_names

    def test_initialization_all_overrides_flags(self, mock_converter):
        tools = DoclingTools(
            all=True,
            enable_convert_to_markdown=False,
            enable_convert_to_text=False,
            enable_convert_to_html=False,
            enable_convert_to_html_split_page=False,
            enable_convert_to_json=False,
            enable_convert_to_yaml=False,
            enable_convert_to_doctags=False,
            enable_convert_to_vtt=False,
            enable_convert_string_content=False,
            enable_list_supported_parsers=False,
        )
        function_names = [func.name for func in tools.functions.values()]
        assert "convert_to_markdown" in function_names
        assert "convert_to_text" in function_names
        assert "convert_to_html" in function_names
        assert "convert_to_html_split_page" in function_names
        assert "convert_to_json" in function_names
        assert "convert_to_yaml" in function_names
        assert "convert_to_doctags" in function_names
        assert "convert_to_vtt" in function_names
        assert "convert_string_content" in function_names
        assert "list_supported_parsers" in function_names


class TestDoclingToolsConversion:
    def test_convert_to_markdown_success(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.return_value = _build_mock_result(markdown="# Doc")

        result = tools.convert_to_markdown("https://example.com/doc.pdf")

        assert result == "# Doc"
        mock_converter.convert.assert_called_once_with(
            "https://example.com/doc.pdf", headers=None, raises_on_error=True
        )

    def test_convert_with_page_and_size_limits(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.return_value = _build_mock_result(text="Ok")

        result = tools.convert_to_text(
            "/tmp/doc.pdf",
            max_num_pages=2,
            max_file_size=1234,
        )

        assert result == "Ok"
        mock_converter.convert.assert_called_once_with(
            "/tmp/doc.pdf",
            headers=None,
            raises_on_error=True,
            max_num_pages=2,
            max_file_size=1234,
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

    def test_convert_to_html_split_page_success(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.return_value = _build_mock_result(html_split_page="<div>Split page html</div>")

        result = tools.convert_to_html_split_page("/tmp/doc.pdf")

        assert result == "<div>Split page html</div>"

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

    def test_convert_to_yaml_success(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.return_value = _build_mock_result()

        result = tools.convert_to_yaml("/tmp/doc.pdf")

        assert "title: Docling" in result

    def test_convert_to_vtt_success(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.return_value = _build_mock_result(vtt="WEBVTT\n\n00:00.000 --> 00:01.000\nHi")

        result = tools.convert_to_vtt("/tmp/doc.pdf")

        assert "WEBVTT" in result

    def test_convert_empty_source(self, mock_converter):
        tools = DoclingTools()
        result = tools.convert_to_markdown("")
        assert result == "Error: No source provided"

    def test_convert_exception(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert.side_effect = Exception("boom")

        result = tools.convert_to_markdown("/tmp/doc.pdf")

        assert result == "Error converting document: boom"

    def test_convert_to_json_truncation_keeps_valid_json(self, mock_converter):
        tools = DoclingTools(max_chars=8)
        mock_converter.convert.return_value = _build_mock_result()

        result = tools.convert_to_json("/tmp/doc.pdf")
        parsed = json.loads(result)

        assert parsed["truncated"] is True
        assert parsed["max_chars"] == 8
        assert parsed["content"].endswith("...")

    def test_convert_string_content_success(self, mock_converter):
        tools = DoclingTools()
        mock_converter.convert_string.return_value = _build_mock_result(markdown="# Parsed from string")

        result = tools.convert_string_content(
            "# Parsed from string", source_format="markdown", output_format="markdown"
        )

        assert result == "# Parsed from string"
        mock_converter.convert_string.assert_called_once()

    def test_convert_string_content_invalid_source_format(self, mock_converter):
        tools = DoclingTools()

        result = tools.convert_string_content("something", source_format="pdf", output_format="markdown")

        assert "Error converting string content" in result

    def test_list_supported_parsers_returns_json(self, mock_converter):
        tools = DoclingTools()

        result = tools.list_supported_parsers()
        parsed = json.loads(result)

        assert "supported_input_parsers" in parsed
        assert "active_allowed_parsers" in parsed
        assert "pdf" in parsed["supported_input_parsers"]


class TestDoclingToolsPdfPipeline:
    def test_pdf_pipeline_options_are_applied(self):
        with patch("agno.tools.docling.DocumentConverter") as mock_converter_cls:
            mock_converter_cls.return_value = Mock()

            DoclingTools(
                pdf_enable_ocr=True,
                pdf_ocr_engine="auto",
                pdf_ocr_lang=["en"],
                pdf_force_full_page_ocr=True,
            )

            _, kwargs = mock_converter_cls.call_args
            assert "format_options" in kwargs
            format_options = kwargs["format_options"]
            assert InputFormat.PDF in format_options
            pdf_format_option = format_options[InputFormat.PDF]
            assert isinstance(pdf_format_option, PdfFormatOption)
            assert isinstance(pdf_format_option.pipeline_options, PdfPipelineOptions)
            assert pdf_format_option.pipeline_options.do_ocr is True
            assert pdf_format_option.pipeline_options.ocr_options is not None

    def test_allowed_input_parsers_are_applied(self):
        with patch("agno.tools.docling.DocumentConverter") as mock_converter_cls:
            mock_converter_cls.return_value = Mock()

            DoclingTools(allowed_input_formats=["pdf", "docx", "markdown"])

            _, kwargs = mock_converter_cls.call_args
            assert "allowed_formats" in kwargs
            assert InputFormat.PDF in kwargs["allowed_formats"]
            assert InputFormat.DOCX in kwargs["allowed_formats"]
            assert InputFormat.MD in kwargs["allowed_formats"]

    def test_invalid_allowed_input_parser_raises(self):
        with pytest.raises(ValueError, match="Invalid input parser"):
            DoclingTools(allowed_input_formats=["not-a-parser"])

    def test_ambiguous_xml_allowed_input_parser_raises(self):
        with pytest.raises(ValueError) as exc_info:
            DoclingTools(allowed_input_formats=["xml"])

        error_message = str(exc_info.value)
        assert "Ambiguous input parser 'xml'" in error_message
        assert "xml_" in error_message

    def test_explicit_xml_allowed_input_parser_is_applied(self):
        with patch("agno.tools.docling.DocumentConverter") as mock_converter_cls:
            mock_converter_cls.return_value = Mock()

            DoclingTools(allowed_input_formats=["xml_uspto"])

            _, kwargs = mock_converter_cls.call_args
            assert "allowed_formats" in kwargs
            assert InputFormat.XML_USPTO in kwargs["allowed_formats"]


class TestDoclingToolsOcrOptions:
    def test_invalid_ocr_engine_raises_error(self, mock_converter):
        tools = DoclingTools()
        with pytest.raises(ValueError, match="Invalid OCR engine"):
            tools._build_ocr_options(
                engine="invalid-engine",
                lang=["en"],
                force_full_page_ocr=None,
            )
