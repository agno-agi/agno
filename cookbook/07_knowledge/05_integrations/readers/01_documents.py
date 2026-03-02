"""
Document Readers: PDF, DOCX, PPTX, Excel
==========================================
Knowledge auto-detects file types and selects the right reader.
You can also specify a reader explicitly for more control.

Supported document formats:
- PDF: Text extraction with optional OCR
- DOCX: Microsoft Word documents
- PPTX: PowerPoint presentations
- Excel: .xlsx and .xls spreadsheets

See also: 02_data.py for CSV/JSON, 03_web.py for web sources.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.excel_reader import ExcelReader

# Other available readers (used via auto-detection or explicit import):
# from agno.knowledge.reader.docx_reader import DocxReader
# from agno.knowledge.reader.pdf_reader import PDFReader
# from agno.knowledge.reader.pptx_reader import PPTXReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="document_readers",
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
        # --- PDF: auto-detected by file extension ---
        print("\n" + "=" * 60)
        print("READER: PDF (auto-detected)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="CV",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
        )
        agent.print_response("What skills does Jordan Mitchell have?", stream=True)

        # --- Excel: explicit reader for more control ---
        print("\n" + "=" * 60)
        print("READER: Excel (explicit reader)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Products",
            path="cookbook/07_knowledge/testing_resources/sample_products.xlsx",
            reader=ExcelReader(),
        )
        agent.print_response("What products are listed?", stream=True)

        # --- PDF from URL: auto-detected ---
        print("\n" + "=" * 60)
        print("READER: PDF from URL")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Recipes",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        )
        agent.print_response("What Thai recipes are available?", stream=True)

    asyncio.run(main())
