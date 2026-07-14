"""
Data Readers: CSV, JSON, Field-Labeled CSV
============================================
Readers for structured data formats. CSV and JSON files are processed
row-by-row or as complete documents.

Supported data formats:
- CSV: Standard comma-separated values
- JSON: JSON files and arrays
- Field-Labeled CSV: CSV with column names as labels in output

See also: 01_documents.py for PDF/DOCX, 03_web.py for web sources.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.csv_reader import CSVReader
from agno.knowledge.reader.json_reader import JSONReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="data_readers",
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
        # --- CSV: structured tabular data ---
        print("\n" + "=" * 60)
        print("READER: CSV")
        print("=" * 60 + "\n")

        # CSVReader reads each row as a separate document
        await knowledge.ainsert(
            name="Sample Data",
            text_content="name,role,department\nAlice,Engineer,Platform\nBob,Designer,Product\nCarol,Manager,Engineering",
            reader=CSVReader(),
        )
        agent.print_response("Who works in engineering?", stream=True)

        # --- JSON: structured data ---
        print("\n" + "=" * 60)
        print("READER: JSON")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Config",
            text_content='{"app": "acme", "version": "2.0", "features": ["auth", "billing", "analytics"]}',
            reader=JSONReader(),
        )
        agent.print_response("What features does the app have?", stream=True)

    asyncio.run(main())
