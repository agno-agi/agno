"""
13. PDF Understanding
=====================
Gemini can read and understand PDF documents.
Pass PDFs via URL -- Gemini fetches and processes them directly.

Run:
    python cookbook/gemini_3/13_pdf_input.py

Example prompt:
    "Summarize this document and suggest a recipe."
"""

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
doc_reader = Agent(
    name="Document Reader",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="You are a document analysis expert. Read documents thoroughly and provide clear summaries.",
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
