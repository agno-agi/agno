"""
PDF Understanding - Read and Analyze Documents
================================================
Pass PDF documents to Gemini for reading and analysis. No parsing libraries needed.

Key concepts:
- File(url=..., mime_type="application/pdf"): Pass a PDF from a URL
- File(filepath=..., mime_type="application/pdf"): Pass a local PDF
- Native capability: No PyPDF, pdfplumber, or other parsing libraries needed
- Layout-aware: The model understands tables, columns, and formatting

Example prompts to try:
- "Summarize the contents of this document"
- "What are the main recipes in this cookbook?"
- "Extract all the key findings from this research paper"
"""

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a document analysis expert. Read documents thoroughly
and provide clear summaries.

## Rules

- Summarize the main points first
- Note any tables or structured data
- Highlight actionable information\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
doc_reader = Agent(
    name="Document Reader",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    doc_reader.print_response(
        "Summarize the contents of this document and suggest a recipe from it.",
        files=[
            File(
                url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
                mime_type="application/pdf",
            )
        ],
        stream=True,
    )

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
PDF input methods:

1. From URL
   files=[File(url="https://example.com/report.pdf", mime_type="application/pdf")]

2. From local file
   files=[File(filepath="path/to/report.pdf", mime_type="application/pdf")]

3. Multiple PDFs
   files=[
       File(url="...", mime_type="application/pdf"),
       File(filepath="...", mime_type="application/pdf"),
   ]

4. With structured output (extract data from PDFs)
   class Report(BaseModel):
       title: str
       key_findings: List[str]
       recommendations: List[str]

   agent = Agent(model=Gemini(...), output_schema=Report)
   result = agent.run("Extract findings", files=[...])

Use cases for music/film/gaming:
- Parse music licensing contracts
- Extract requirements from game design documents
- Analyze film scripts for scene breakdowns
"""
