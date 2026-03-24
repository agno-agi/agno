from agno.agent import Agent
from agno.tools.docling import DoclingTools

from paths import pdf_path


def run_ocr_example() -> None:
    # pdf_ocr_engine accepts: auto | easyocr | tesseract | tesseract_cli | ocrmac | rapidocr
    # Some engines may require extra runtime dependencies in your environment.
    ocr_tools = DoclingTools(
        pdf_enable_ocr=True,
        pdf_ocr_engine="easyocr",
        pdf_ocr_lang=["pt", "en"],
        pdf_force_full_page_ocr=True,
        pdf_enable_table_structure=True,
        pdf_enable_picture_description=False,
        pdf_document_timeout=120.0,
    )

    ocr_agent = Agent(
        tools=[ocr_tools],
        description="You are an agent that converts PDFs using advanced OCR.",
    )

    ocr_agent.print_response(
        f"Convert to Markdown: {pdf_path}",
        markdown=True,
    )
