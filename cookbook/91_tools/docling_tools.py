from dotenv import load_dotenv

from agno.agent import Agent
from agno.tools.docling import DoclingTools

load_dotenv()

agent = Agent(
    tools=[DoclingTools()],
    description="You are an agent that converts documents to Markdown, text, HTML, JSON, or DocTags.",
)

# URL or local path
agent.print_response(
    "Convert to Markdown: https://www.orimi.com/pdf-test.pdf",
    markdown=True,
)
agent.print_response(
    "Convert to JSON and return the full JSON without summarizing: https://www.orimi.com/pdf-test.pdf",
    markdown=True,
)
agent.print_response(
    "Convert to DocTags: https://www.orimi.com/pdf-test.pdf",
    markdown=True,
)


# Local example (adjust the path)
# agent.print_response("Convert to text: ./documents/report.pdf", markdown=True)

# Example with advanced PDF/OCR options
# pdf_ocr_engine accepts: auto | easyocr | tesseract | tesseract_cli | ocrmac | rapidocr
ocr_tools = DoclingTools(
    pdf_do_ocr=True,
    pdf_ocr_engine="easyocr",
    pdf_ocr_lang=["pt", "en"],
    pdf_force_full_page_ocr=True,
    pdf_do_table_structure=True,
    pdf_do_picture_description=False,
    pdf_document_timeout=120.0,
)

ocr_agent = Agent(
    tools=[ocr_tools],
    description="You are an agent that converts PDFs using advanced OCR.",
)

# ocr_agent.print_response(
#     "Convert to Markdown: https://www.orimi.com/pdf-test.pdf",
#     markdown=True,
# )
