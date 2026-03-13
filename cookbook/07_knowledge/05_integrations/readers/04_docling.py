"""
Docling Reader: Advanced Document Understanding
================================================
Docling uses IBM's advanced document conversion library to extract content from multiple document formats.

Supported formats examples::
- PDF: PDFs with advanced layout understanding and text extraction
- DOCX: Microsoft Word documents with structure preservation
- PPTX: PowerPoint presentations
- Markdown: Markdown files
- CSV: CSV spreadsheets
- XLSX: Excel spreadsheets

Output formats examples:
- markdown: Preserves structure and formatting
- text: Plain text output
- json: Lossless serialization with full document structure
- html: HTML with image embedding/referencing support
- doctags: Markup format with full content and layout characteristics

Key features:
- Advanced document structure understanding
- Better handling of complex layouts (tables, columns, etc.)
- Multiple output formats for different use cases
- Ideal for complex documents with rich formatting

Run `uv pip install docling` to install dependencies.

See also: 01_documents.py for PDF/DOCX, 02_data.py for CSV/JSON and 03_web.py for web sources.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.docling_reader import DoclingReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="docling_reader",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # --- Local PDF file with markdown output ---
        print("\n" + "=" * 60)
        print("Local PDF file (markdown output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="CV_Local",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            reader=DoclingReader(output_format="markdown"),
        )
        agent.print_response("What skills does Jordan Mitchell have?", stream=True)

        # --- PDF from URL with text output ---
        print("\n" + "=" * 60)
        print("PDF from URL (text output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Recipes_URL",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            reader=DoclingReader(output_format="text"),
        )
        agent.print_response("What Thai recipes are available?", stream=True)

        # --- ArXiv paper from URL with md output---
        print("\n" + "=" * 60)
        print("ArXiv paper from URL (markdown output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Docling_Paper",
            url="https://arxiv.org/pdf/2408.09869",
            reader=DoclingReader(output_format="markdown"),
        )
        agent.print_response(
            "What is Docling and what are its key features?", stream=True
        )

        # --- JSON output for structured data ---
        print("\n" + "=" * 60)
        print("PDF with JSON output")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Structured_Doc",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            reader=DoclingReader(output_format="json"),
        )
        agent.print_response(
            "What is the structure of this document?",
            stream=True,
        )

        # --- PDF with HTML output ---
        print("\n" + "=" * 60)
        print("PDF with HTML output")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="HTML_Doc",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            reader=DoclingReader(output_format="html"),
        )
        agent.print_response(
            "Summarize the candidate's experience",
            stream=True,
        )

        # --- PDF with Doctags output ---
        print("\n" + "=" * 60)
        print("PDF with Doctags output")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Doctags_Doc",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            reader=DoclingReader(output_format="doctags"),
        )
        agent.print_response(
            "What sections are in this document?",
            stream=True,
        )

    asyncio.run(main())
