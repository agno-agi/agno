"""
Docling Reader: Data Files
===========================
Examples of using Docling to process spreadsheet and data files.

Supported formats:
- XLSX: Microsoft Excel spreadsheets
- CSV: Comma-separated values files

Docling preserves table structure and formatting from spreadsheets.

Run `uv pip install docling openai-whisper` to install dependencies.
"""

import asyncio

from agno.knowledge.reader.docling_reader import DoclingReader
from utils import get_agent, get_knowledge

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

knowledge = get_knowledge(table_name="docling_data")
agent = get_agent(knowledge)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # --- XLSX file - Sample products with HTML output ---
        print("\n" + "=" * 60)
        print("XLSX file - Sample Products (HTML output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Sample_Products",
            path="cookbook/07_knowledge/testing_resources/sample_products.xlsx",
            reader=DoclingReader(output_format="html"),
        )
        agent.print_response(
            "What products are available and what are their prices?",
            stream=True,
        )

    asyncio.run(main())
