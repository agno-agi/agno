import json
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        EasyOcrOptions,
        OcrAutoOptions,
        OcrMacOptions,
        PdfPipelineOptions,
        RapidOcrOptions,
        TesseractCliOcrOptions,
        TesseractOcrOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption
except ImportError:
    raise ImportError("`docling` not installed. Please install using `pip install docling`")


class DoclingTools(Toolkit):
    """
    Toolkit for converting documents with Docling.

    Supports local files and URLs. Export formats: markdown, text, html, html_split_page,
    json, yaml, doctags, and vtt.
    Advanced pipeline/OCR options can be configured via init params.

    PDF/OCR options (init args):
    - pdf_enable_ocr: bool
    - pdf_ocr_engine: "auto" | "easyocr" | "tesseract" | "tesseract_cli" | "ocrmac" | "rapidocr"
    - pdf_ocr_lang: list of language codes
    - pdf_force_full_page_ocr: bool
    - pdf_enable_table_structure: bool
    - pdf_enable_picture_description: bool
    - pdf_enable_picture_classification: bool
    - pdf_document_timeout: float (seconds)
    - pdf_enable_remote_services: bool

    Note:
    Some OCR engines may require additional runtime dependencies. For example,
    `easyocr` can require installing EasyOCR and its model/runtime stack in the
    active environment.
    """

    def __init__(
        self,
        converter: Optional[DocumentConverter] = None,
        max_chars: Optional[int] = None,
        allowed_input_formats: Optional[List[str]] = None,
        format_options: Optional[Dict[Any, Any]] = None,
        pdf_pipeline_options: Optional[PdfPipelineOptions] = None,
        pdf_enable_ocr: Optional[bool] = None,
        pdf_ocr_engine: Optional[str] = None,
        pdf_ocr_lang: Optional[List[str]] = None,
        pdf_force_full_page_ocr: Optional[bool] = None,
        pdf_enable_table_structure: Optional[bool] = None,
        pdf_enable_picture_description: Optional[bool] = None,
        pdf_enable_picture_classification: Optional[bool] = None,
        pdf_document_timeout: Optional[float] = None,
        pdf_enable_remote_services: Optional[bool] = None,
        enable_convert_to_markdown: bool = True,
        enable_convert_to_text: bool = True,
        enable_convert_to_html: bool = True,
        enable_convert_to_html_split_page: bool = True,
        enable_convert_to_json: bool = True,
        enable_convert_to_yaml: bool = True,
        enable_convert_to_doctags: bool = True,
        enable_convert_to_vtt: bool = True,
        enable_convert_string_content: bool = True,
        enable_list_supported_parsers: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.converter: DocumentConverter = converter or self._build_converter(
            allowed_input_formats=allowed_input_formats,
            format_options=format_options,
            pdf_pipeline_options=pdf_pipeline_options,
            pdf_enable_ocr=pdf_enable_ocr,
            pdf_ocr_engine=pdf_ocr_engine,
            pdf_ocr_lang=pdf_ocr_lang,
            pdf_force_full_page_ocr=pdf_force_full_page_ocr,
            pdf_enable_table_structure=pdf_enable_table_structure,
            pdf_enable_picture_description=pdf_enable_picture_description,
            pdf_enable_picture_classification=pdf_enable_picture_classification,
            pdf_document_timeout=pdf_document_timeout,
            pdf_enable_remote_services=pdf_enable_remote_services,
        )
        self.max_chars = max_chars

        tools: List[Any] = []
        if all or enable_convert_to_markdown:
            tools.append(self.convert_to_markdown)
        if all or enable_convert_to_text:
            tools.append(self.convert_to_text)
        if all or enable_convert_to_html:
            tools.append(self.convert_to_html)
        if all or enable_convert_to_html_split_page:
            tools.append(self.convert_to_html_split_page)
        if all or enable_convert_to_json:
            tools.append(self.convert_to_json)
        if all or enable_convert_to_yaml:
            tools.append(self.convert_to_yaml)
        if all or enable_convert_to_doctags:
            tools.append(self.convert_to_doctags)
        if all or enable_convert_to_vtt:
            tools.append(self.convert_to_vtt)
        if all or enable_convert_string_content:
            tools.append(self.convert_string_content)
        if all or enable_list_supported_parsers:
            tools.append(self.list_supported_parsers)

        super().__init__(name="docling_tools", tools=tools, **kwargs)

    def convert_to_markdown(
        self,
        source: str,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        """Convert a local file or URL to Markdown format using Docling.

        Args:
            source (str): Local file path or URL to the document.
            headers (Optional[Dict[str, str]]): Optional HTTP headers used for URL fetching.
            raises_on_error (bool): If True, raises conversion exceptions in Docling internals.
            max_num_pages (Optional[int]): Maximum number of pages to process from the source.
            max_file_size (Optional[int]): Maximum file size in bytes allowed for processing.

        Returns:
            str: The converted Markdown content, or an error message if conversion fails.
        """
        return self._convert_and_export(
            source,
            export_format="markdown",
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
        )

    def convert_to_text(
        self,
        source: str,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        """Convert a local file or URL to plain text format using Docling.

        Args:
            source (str): Local file path or URL to the document.
            headers (Optional[Dict[str, str]]): Optional HTTP headers used for URL fetching.
            raises_on_error (bool): If True, raises conversion exceptions in Docling internals.
            max_num_pages (Optional[int]): Maximum number of pages to process from the source.
            max_file_size (Optional[int]): Maximum file size in bytes allowed for processing.

        Returns:
            str: The converted plain text content, or an error message if conversion fails.
        """
        return self._convert_and_export(
            source,
            export_format="text",
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
        )

    def convert_to_html(
        self,
        source: str,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        """Convert a local file or URL to HTML format using Docling.

        Args:
            source (str): Local file path or URL to the document.
            headers (Optional[Dict[str, str]]): Optional HTTP headers used for URL fetching.
            raises_on_error (bool): If True, raises conversion exceptions in Docling internals.
            max_num_pages (Optional[int]): Maximum number of pages to process from the source.
            max_file_size (Optional[int]): Maximum file size in bytes allowed for processing.

        Returns:
            str: The converted HTML content, or an error message if conversion fails.
        """
        return self._convert_and_export(
            source,
            export_format="html",
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
        )

    def convert_to_html_split_page(
        self,
        source: str,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        """Convert a local file or URL to split-page HTML format using Docling.

        Args:
            source (str): Local file path or URL to the document.
            headers (Optional[Dict[str, str]]): Optional HTTP headers used for URL fetching.
            raises_on_error (bool): If True, raises conversion exceptions in Docling internals.
            max_num_pages (Optional[int]): Maximum number of pages to process from the source.
            max_file_size (Optional[int]): Maximum file size in bytes allowed for processing.

        Returns:
            str: The converted split-page HTML content, or an error message if conversion fails.
        """
        return self._convert_and_export(
            source,
            export_format="html_split_page",
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
        )

    def convert_to_json(
        self,
        source: str,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        """Convert a local file or URL to JSON format using Docling.

        Args:
            source (str): Local file path or URL to the document.
            headers (Optional[Dict[str, str]]): Optional HTTP headers used for URL fetching.
            raises_on_error (bool): If True, raises conversion exceptions in Docling internals.
            max_num_pages (Optional[int]): Maximum number of pages to process from the source.
            max_file_size (Optional[int]): Maximum file size in bytes allowed for processing.

        Returns:
            str: The converted JSON content, or an error message if conversion fails.
        """
        return self._convert_and_export(
            source,
            export_format="json",
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
        )

    def convert_to_yaml(
        self,
        source: str,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        """Convert a local file or URL to YAML format using Docling.

        Args:
            source (str): Local file path or URL to the document.
            headers (Optional[Dict[str, str]]): Optional HTTP headers used for URL fetching.
            raises_on_error (bool): If True, raises conversion exceptions in Docling internals.
            max_num_pages (Optional[int]): Maximum number of pages to process from the source.
            max_file_size (Optional[int]): Maximum file size in bytes allowed for processing.

        Returns:
            str: The converted YAML content, or an error message if conversion fails.
        """
        return self._convert_and_export(
            source,
            export_format="yaml",
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
        )

    def convert_to_doctags(
        self,
        source: str,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        """Convert a local file or URL to DocTags format using Docling.

        Args:
            source (str): Local file path or URL to the document.
            headers (Optional[Dict[str, str]]): Optional HTTP headers used for URL fetching.
            raises_on_error (bool): If True, raises conversion exceptions in Docling internals.
            max_num_pages (Optional[int]): Maximum number of pages to process from the source.
            max_file_size (Optional[int]): Maximum file size in bytes allowed for processing.

        Returns:
            str: The converted DocTags content, or an error message if conversion fails.
        """
        return self._convert_and_export(
            source,
            export_format="doctags",
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
        )

    def convert_to_vtt(
        self,
        source: str,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        """Convert a local file or URL to VTT format using Docling.

        Args:
            source (str): Local file path or URL to the document.
            headers (Optional[Dict[str, str]]): Optional HTTP headers used for URL fetching.
            raises_on_error (bool): If True, raises conversion exceptions in Docling internals.
            max_num_pages (Optional[int]): Maximum number of pages to process from the source.
            max_file_size (Optional[int]): Maximum file size in bytes allowed for processing.

        Returns:
            str: The converted VTT content, or an error message if conversion fails.
        """
        return self._convert_and_export(
            source,
            export_format="vtt",
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
        )

    def convert_string_content(
        self,
        content: str,
        source_format: str = "markdown",
        output_format: str = "markdown",
        name: Optional[str] = None,
    ) -> str:
        """Convert raw markdown or HTML string content using Docling convert_string.

        Args:
            content (str): Raw source content to convert.
            source_format (str): Input content format, one of markdown, md, or html.
            output_format (str): Export format used after conversion.
            name (Optional[str]): Optional document name associated with this in-memory source.

        Returns:
            str: Converted content in the selected output format, or an error message if conversion fails.
        """
        if not content:
            return "Error: No content provided"

        try:
            input_format = self._resolve_string_input_format(source_format)
            result = self.converter.convert_string(content=content, format=input_format, name=name)
            exported_content = self._export_document(result.document, output_format)
            return self._truncate_content(exported_content, output_format)
        except Exception as e:
            log_error(f"Error converting string content: {e}")
            return f"Error converting string content: {e}"

    def list_supported_parsers(self) -> str:
        """List all Docling-supported input parsers and active converter parser restrictions.

        Returns:
            str: A JSON payload with supported_input_parsers and active_allowed_parsers fields.
        """
        all_supported = sorted([input_format.name.lower() for input_format in InputFormat])
        converter_allowed_formats = getattr(self.converter, "allowed_formats", None)
        if isinstance(converter_allowed_formats, list):
            active_formats = sorted([input_format.name.lower() for input_format in converter_allowed_formats])
        else:
            active_formats = all_supported
        payload = {
            "supported_input_parsers": all_supported,
            "active_allowed_parsers": active_formats,
        }
        return json.dumps(payload, indent=2)

    def _convert_and_export(
        self,
        source: str,
        export_format: str,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        if not source:
            return "Error: No source provided"

        try:
            log_debug(f"Converting document with Docling: {source}")
            convert_kwargs: Dict[str, Any] = {
                "headers": headers,
                "raises_on_error": raises_on_error,
            }
            if max_num_pages is not None:
                convert_kwargs["max_num_pages"] = max_num_pages
            if max_file_size is not None:
                convert_kwargs["max_file_size"] = max_file_size

            result = self.converter.convert(source, **convert_kwargs)
            content = self._export_document(result.document, export_format)

            return self._truncate_content(content, export_format)
        except Exception as e:
            log_error(f"Error converting document: {e}")
            return f"Error converting document: {e}"

    def _export_document(self, document: Any, export_format: str) -> str:
        if export_format == "markdown":
            return document.export_to_markdown()
        if export_format == "text":
            return document.export_to_text()
        if export_format == "html":
            return document.export_to_html()
        if export_format == "html_split_page":
            return document.export_to_html(split_page_view=True)
        if export_format == "json":
            return json.dumps(document.export_to_dict(), indent=2)
        if export_format == "yaml":
            import yaml

            return yaml.safe_dump(document.export_to_dict())
        if export_format == "doctags":
            return document.export_to_doctags()
        if export_format == "vtt":
            document_obj: Any = document
            export_to_vtt = getattr(document_obj, "export_to_vtt", None)
            if not callable(export_to_vtt):
                raise ValueError("VTT export is not supported by the installed docling version")
            vtt_content = export_to_vtt()
            return vtt_content if isinstance(vtt_content, str) else str(vtt_content)

        raise ValueError(f"Unsupported export format {export_format}")

    def _resolve_string_input_format(self, source_format: str) -> Any:
        source_format_value = source_format.lower().strip()
        if source_format_value in ["markdown", "md"]:
            return InputFormat.MD
        if source_format_value == "html":
            return InputFormat.HTML
        raise ValueError("source_format must be one of: markdown, md, html")

    def _build_converter(
        self,
        allowed_input_formats: Optional[List[str]],
        format_options: Optional[Dict[Any, Any]],
        pdf_pipeline_options: Optional[PdfPipelineOptions],
        pdf_enable_ocr: Optional[bool],
        pdf_ocr_engine: Optional[str],
        pdf_ocr_lang: Optional[List[str]],
        pdf_force_full_page_ocr: Optional[bool],
        pdf_enable_table_structure: Optional[bool],
        pdf_enable_picture_description: Optional[bool],
        pdf_enable_picture_classification: Optional[bool],
        pdf_document_timeout: Optional[float],
        pdf_enable_remote_services: Optional[bool],
    ) -> DocumentConverter:
        options = dict(format_options or {})
        resolved_allowed_formats = self._resolve_allowed_input_formats(allowed_input_formats)

        pdf_options = self._build_pdf_pipeline_options(
            pdf_pipeline_options=pdf_pipeline_options,
            pdf_enable_ocr=pdf_enable_ocr,
            pdf_ocr_engine=pdf_ocr_engine,
            pdf_ocr_lang=pdf_ocr_lang,
            pdf_force_full_page_ocr=pdf_force_full_page_ocr,
            pdf_enable_table_structure=pdf_enable_table_structure,
            pdf_enable_picture_description=pdf_enable_picture_description,
            pdf_enable_picture_classification=pdf_enable_picture_classification,
            pdf_document_timeout=pdf_document_timeout,
            pdf_enable_remote_services=pdf_enable_remote_services,
        )
        if pdf_options:
            options[InputFormat.PDF] = PdfFormatOption(pipeline_options=pdf_options)

        converter_kwargs: Dict[str, Any] = {}
        if resolved_allowed_formats is not None:
            converter_kwargs["allowed_formats"] = resolved_allowed_formats
        if options:
            converter_kwargs["format_options"] = options

        if converter_kwargs:
            return DocumentConverter(**converter_kwargs)
        return DocumentConverter()

    def _resolve_allowed_input_formats(self, allowed_input_formats: Optional[List[str]]) -> Optional[List[InputFormat]]:
        if allowed_input_formats is None:
            return None

        alias_map = {
            "markdown": "md",
        }
        resolved_formats: List[InputFormat] = []
        valid_names = sorted([input_format.name.lower() for input_format in InputFormat])

        for input_format_name in allowed_input_formats:
            normalized_name = input_format_name.lower().strip()

            if normalized_name == "xml":
                xml_variants = [name for name in valid_names if name.startswith("xml_")]
                variants_message = ", ".join(xml_variants) if xml_variants else "explicit xml_* parser"
                raise ValueError(f"Ambiguous input parser 'xml'. Use one of: {variants_message}.")

            normalized_name = alias_map.get(normalized_name, normalized_name)

            resolved = None
            for input_format in InputFormat:
                if input_format.name.lower() == normalized_name:
                    resolved = input_format
                    break

            if resolved is None:
                raise ValueError(
                    f"Invalid input parser '{input_format_name}'. Expected one of: {', '.join(valid_names)}"
                )

            resolved_formats.append(resolved)

        return resolved_formats

    def _build_pdf_pipeline_options(
        self,
        pdf_pipeline_options: Optional[PdfPipelineOptions],
        pdf_enable_ocr: Optional[bool],
        pdf_ocr_engine: Optional[str],
        pdf_ocr_lang: Optional[List[str]],
        pdf_force_full_page_ocr: Optional[bool],
        pdf_enable_table_structure: Optional[bool],
        pdf_enable_picture_description: Optional[bool],
        pdf_enable_picture_classification: Optional[bool],
        pdf_document_timeout: Optional[float],
        pdf_enable_remote_services: Optional[bool],
    ) -> Optional[PdfPipelineOptions]:
        if pdf_pipeline_options is not None:
            return pdf_pipeline_options

        if (
            pdf_enable_ocr is None
            and pdf_ocr_engine is None
            and pdf_ocr_lang is None
            and pdf_force_full_page_ocr is None
            and pdf_enable_table_structure is None
            and pdf_enable_picture_description is None
            and pdf_enable_picture_classification is None
            and pdf_document_timeout is None
            and pdf_enable_remote_services is None
        ):
            return None

        options = PdfPipelineOptions()
        if pdf_enable_ocr is not None:
            options.do_ocr = pdf_enable_ocr
        if pdf_enable_table_structure is not None:
            options.do_table_structure = pdf_enable_table_structure
        if pdf_enable_picture_description is not None:
            options.do_picture_description = pdf_enable_picture_description
        if pdf_enable_picture_classification is not None:
            options.do_picture_classification = pdf_enable_picture_classification
        if pdf_document_timeout is not None:
            options.document_timeout = pdf_document_timeout
        if pdf_enable_remote_services is not None:
            options.enable_remote_services = pdf_enable_remote_services

        ocr_options = self._build_ocr_options(
            engine=pdf_ocr_engine,
            lang=pdf_ocr_lang,
            force_full_page_ocr=pdf_force_full_page_ocr,
        )
        if ocr_options is not None:
            options.ocr_options = ocr_options
            if pdf_enable_ocr is None:
                options.do_ocr = True

        return options

    def _build_ocr_options(
        self,
        engine: Optional[str],
        lang: Optional[List[str]],
        force_full_page_ocr: Optional[bool],
    ) -> Optional[Any]:
        if not engine:
            return None

        engine_value = engine.lower()
        languages = lang or []
        kwargs: Dict[str, Any] = {"lang": languages}
        if force_full_page_ocr is not None:
            kwargs["force_full_page_ocr"] = force_full_page_ocr

        engine_map = {
            "auto": OcrAutoOptions,
            "easyocr": EasyOcrOptions,
            "tesseract": TesseractOcrOptions,
            "tesseract_cli": TesseractCliOcrOptions,
            "ocrmac": OcrMacOptions,
            "rapidocr": RapidOcrOptions,
        }

        ocr_cls = engine_map.get(engine_value)
        if ocr_cls is not None:
            dependency_hints = {
                "easyocr": "Install optional dependencies, e.g. `uv pip install easyocr`.",
                "tesseract": "Install the Python tesseract dependencies and ensure tesseract OCR is available.",
                "tesseract_cli": "Install the tesseract CLI binary and ensure it is available on PATH.",
                "rapidocr": "Install optional dependencies, e.g. `uv pip install rapidocr_onnxruntime`.",
                "ocrmac": "OCRMac is only available on macOS with required native dependencies.",
            }
            try:
                return ocr_cls(**kwargs)
            except Exception as e:
                hint = dependency_hints.get(engine_value, "Install required OCR runtime dependencies for this engine.")
                raise RuntimeError(f"Failed to initialize OCR engine '{engine}'. {hint}") from e

        valid_engines = list(engine_map.keys())
        raise ValueError(f"Invalid OCR engine '{engine}'. Expected one of: {', '.join(valid_engines)}.")

    def _truncate_content(self, content: str, export_format: str) -> str:
        if self.max_chars and len(content) > self.max_chars:
            if export_format == "json":
                # Keep JSON output valid even when truncating long content.
                truncated_payload = {
                    "truncated": True,
                    "max_chars": self.max_chars,
                    "content": content[: self.max_chars] + "...",
                }
                return json.dumps(truncated_payload, indent=2)
            if export_format == "yaml":
                import yaml

                truncated_payload = {
                    "truncated": True,
                    "max_chars": self.max_chars,
                    "content": content[: self.max_chars] + "...",
                }
                return yaml.safe_dump(truncated_payload)
            return content[: self.max_chars] + "..."
        return content
