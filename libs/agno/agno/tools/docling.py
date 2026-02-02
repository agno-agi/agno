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

    Supports local files and URLs. Export formats: markdown, text, html, json, doctags.
    Advanced pipeline/OCR options can be configured via init params.

    PDF/OCR options (init args):
    - pdf_do_ocr: bool
    - pdf_ocr_engine: "auto" | "easyocr" | "tesseract" | "tesseract_cli" | "ocrmac" | "rapidocr"
    - pdf_ocr_lang: list of language codes
    - pdf_force_full_page_ocr: bool
    - pdf_do_table_structure: bool
    - pdf_do_picture_description: bool
    - pdf_do_picture_classification: bool
    - pdf_document_timeout: float (seconds)
    - pdf_enable_remote_services: bool
    """

    def __init__(
        self,
        converter: Optional[DocumentConverter] = None,
        max_chars: Optional[int] = None,
        format_options: Optional[Dict[Any, Any]] = None,
        pdf_pipeline_options: Optional[PdfPipelineOptions] = None,
        pdf_do_ocr: Optional[bool] = None,
        pdf_ocr_engine: Optional[str] = None,
        pdf_ocr_lang: Optional[List[str]] = None,
        pdf_force_full_page_ocr: Optional[bool] = None,
        pdf_do_table_structure: Optional[bool] = None,
        pdf_do_picture_description: Optional[bool] = None,
        pdf_do_picture_classification: Optional[bool] = None,
        pdf_document_timeout: Optional[float] = None,
        pdf_enable_remote_services: Optional[bool] = None,
        enable_convert_to_markdown: bool = True,
        enable_convert_to_text: bool = True,
        enable_convert_to_html: bool = True,
        enable_convert_to_json: bool = True,
        enable_convert_to_doctags: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.converter: DocumentConverter = converter or self._build_converter(
            format_options=format_options,
            pdf_pipeline_options=pdf_pipeline_options,
            pdf_do_ocr=pdf_do_ocr,
            pdf_ocr_engine=pdf_ocr_engine,
            pdf_ocr_lang=pdf_ocr_lang,
            pdf_force_full_page_ocr=pdf_force_full_page_ocr,
            pdf_do_table_structure=pdf_do_table_structure,
            pdf_do_picture_description=pdf_do_picture_description,
            pdf_do_picture_classification=pdf_do_picture_classification,
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
        if all or enable_convert_to_json:
            tools.append(self.convert_to_json)
        if all or enable_convert_to_doctags:
            tools.append(self.convert_to_doctags)

        super().__init__(name="docling_tools", tools=tools, **kwargs)

    def convert_to_markdown(
        self,
        source: str,
        headers: Optional[Dict[str, str]] = None,
        raises_on_error: bool = True,
        max_num_pages: Optional[int] = None,
        max_file_size: Optional[int] = None,
    ) -> str:
        """Convert a local file or URL to Markdown."""
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
        """Convert a local file or URL to plain text."""
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
        """Convert a local file or URL to HTML."""
        return self._convert_and_export(
            source,
            export_format="html",
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
        """Convert a local file or URL to a JSON representation."""
        return self._convert_and_export(
            source,
            export_format="json",
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
        """Convert a local file or URL to DocTags representation."""
        return self._convert_and_export(
            source,
            export_format="doctags",
            headers=headers,
            raises_on_error=raises_on_error,
            max_num_pages=max_num_pages,
            max_file_size=max_file_size,
        )

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
            document = result.document

            if export_format == "markdown":
                content = document.export_to_markdown()
            elif export_format == "text":
                content = document.export_to_text()
            elif export_format == "html":
                content = document.export_to_html()
            elif export_format == "json":
                content = json.dumps(document.export_to_dict(), indent=2)
            elif export_format == "doctags":
                content = document.export_to_doctags()
            else:
                return f"Error: Unsupported export format {export_format}"

            return self._truncate_content(content)
        except Exception as e:
            log_error(f"Error converting document: {e}")
            return f"Error converting document: {e}"

    def _build_converter(
        self,
        format_options: Optional[Dict[Any, Any]],
        pdf_pipeline_options: Optional[PdfPipelineOptions],
        pdf_do_ocr: Optional[bool],
        pdf_ocr_engine: Optional[str],
        pdf_ocr_lang: Optional[List[str]],
        pdf_force_full_page_ocr: Optional[bool],
        pdf_do_table_structure: Optional[bool],
        pdf_do_picture_description: Optional[bool],
        pdf_do_picture_classification: Optional[bool],
        pdf_document_timeout: Optional[float],
        pdf_enable_remote_services: Optional[bool],
    ) -> DocumentConverter:
        options = dict(format_options or {})

        pdf_options = self._build_pdf_pipeline_options(
            pdf_pipeline_options=pdf_pipeline_options,
            pdf_do_ocr=pdf_do_ocr,
            pdf_ocr_engine=pdf_ocr_engine,
            pdf_ocr_lang=pdf_ocr_lang,
            pdf_force_full_page_ocr=pdf_force_full_page_ocr,
            pdf_do_table_structure=pdf_do_table_structure,
            pdf_do_picture_description=pdf_do_picture_description,
            pdf_do_picture_classification=pdf_do_picture_classification,
            pdf_document_timeout=pdf_document_timeout,
            pdf_enable_remote_services=pdf_enable_remote_services,
        )
        if pdf_options:
            options[InputFormat.PDF] = PdfFormatOption(pipeline_options=pdf_options)

        if options:
            return DocumentConverter(format_options=options)
        return DocumentConverter()

    def _build_pdf_pipeline_options(
        self,
        pdf_pipeline_options: Optional[PdfPipelineOptions],
        pdf_do_ocr: Optional[bool],
        pdf_ocr_engine: Optional[str],
        pdf_ocr_lang: Optional[List[str]],
        pdf_force_full_page_ocr: Optional[bool],
        pdf_do_table_structure: Optional[bool],
        pdf_do_picture_description: Optional[bool],
        pdf_do_picture_classification: Optional[bool],
        pdf_document_timeout: Optional[float],
        pdf_enable_remote_services: Optional[bool],
    ) -> Optional[PdfPipelineOptions]:
        if pdf_pipeline_options is not None:
            return pdf_pipeline_options

        if (
            pdf_do_ocr is None
            and pdf_ocr_engine is None
            and pdf_ocr_lang is None
            and pdf_force_full_page_ocr is None
            and pdf_do_table_structure is None
            and pdf_do_picture_description is None
            and pdf_do_picture_classification is None
            and pdf_document_timeout is None
            and pdf_enable_remote_services is None
        ):
            return None

        options = PdfPipelineOptions()
        if pdf_do_ocr is not None:
            options.do_ocr = pdf_do_ocr
        if pdf_do_table_structure is not None:
            options.do_table_structure = pdf_do_table_structure
        if pdf_do_picture_description is not None:
            options.do_picture_description = pdf_do_picture_description
        if pdf_do_picture_classification is not None:
            options.do_picture_classification = pdf_do_picture_classification
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
            if pdf_do_ocr is None:
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
            return ocr_cls(**kwargs)

        valid_engines = list(engine_map.keys())
        log_error(f"Invalid OCR engine '{engine}'. Expected one of: {', '.join(valid_engines)}.")
        return None

    def _truncate_content(self, content: str) -> str:
        if self.max_chars and len(content) > self.max_chars:
            return content[: self.max_chars] + "..."
        return content
