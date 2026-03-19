from agno.agent import Agent
from agno.tools.docling import DoclingTools

pdf_path = "cookbook/07_knowledge/testing_resources/cv_1.pdf"
docx_path = "cookbook/07_knowledge/testing_resources/project_proposal.docx"
md_path = "cookbook/07_knowledge/testing_resources/coffee.md"
html_path = "cookbook/07_knowledge/testing_resources/company_info.html"
xml_path = "cookbook/07_knowledge/testing_resources/patent_sample.xml"
xlsx_path = "cookbook/07_knowledge/testing_resources/sample_products.xlsx"
audio_video_path = "cookbook/07_knowledge/testing_resources/agno_description.mp4"

agent = Agent(
    tools=[DoclingTools(all=True)],
    description="You are an agent that converts documents from all Docling parsers and exports to all supported output formats.",
)

agent.print_response(
    "List supported Docling input parsers and active allowed parsers.",
    markdown=True,
)

agent.print_response(
    f"Convert to Markdown: {pdf_path}",
    markdown=True,
)
agent.print_response(
    f"Convert to JSON and return the full JSON without summarizing: {pdf_path}",
    markdown=True,
)
agent.print_response(
    f"Convert to YAML: {pdf_path}",
    markdown=True,
)
agent.print_response(
    f"Convert to DocTags: {pdf_path}",
    markdown=True,
)
agent.print_response(
    f"Convert to VTT: {pdf_path}",
    markdown=True,
)
agent.print_response(
    f"Convert to HTML split page: {pdf_path}",
    markdown=True,
)

# Additional parser examples based on static resources.
agent.print_response(
    f"Convert to Markdown: {docx_path}",
    markdown=True,
)
agent.print_response(
    f"Convert to Markdown: {md_path}",
    markdown=True,
)
agent.print_response(
    f"Convert to Markdown: {html_path}",
    markdown=True,
)
agent.print_response(
    f"Convert to Markdown: {xml_path}",
    markdown=True,
)
agent.print_response(
    f"Convert to Markdown: {xlsx_path}",
    markdown=True,
)
agent.print_response(
    f"Convert to VTT: {audio_video_path}",
    markdown=True,
)

# convert_string is limited by Docling to Markdown and HTML source content.
agent.print_response(
    "Use convert_string_content to convert this markdown string to JSON: # Inline Markdown\n\nThis is a parser test.",
    markdown=True,
)
agent.print_response(
    "Use convert_string_content to convert this html string to Markdown: <h1>Inline HTML</h1><p>This is a parser test.</p>",
    markdown=True,
)

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

ocr_agent.print_response(
    f"Convert to Markdown: {pdf_path}",
    markdown=True,
)
