"""
FileGenerator Agent
===================

Generates downloadable files (JSON, CSV, PDF, DOCX, TXT, HTML) from prompts
using the FileGenerationTools toolkit. Files are returned as base64-encoded
artifacts on the AgentOS response and also saved to ``data/file_gen_out/``.
"""

from pathlib import Path

from agno.agent import Agent
from agno.tools.file_generation import FileGenerationTools
from db import get_db
from settings import default_model

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "file_gen_out"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


FILE_GENERATOR_INSTRUCTIONS = """\
You generate files on request. Pick the right tool for the format the
user asked for:

- generate_json_file for JSON
- generate_csv_file for CSV
- generate_pdf_file for PDF
- generate_docx_file for DOCX
- generate_text_file for plain text
- generate_html_file for HTML — always produce a complete HTML5
  document with doctype, html, head, and body tags.

Always provide meaningful content and a descriptive filename. Briefly
explain what was generated.
"""


file_generator = Agent(
    id="file_generator",
    name="FileGenerator",
    model=default_model(),
    db=get_db(),
    tools=[
        FileGenerationTools(
            all=True,
            output_directory=str(OUTPUT_DIR),
        )
    ],
    instructions=FILE_GENERATOR_INSTRUCTIONS,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)
