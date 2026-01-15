"""Load CSV files with custom encoding using async methods.

Many business systems export CSV files in non-UTF-8 encodings:
- European systems: Latin-1 (ISO-8859-1)
- Chinese systems: GB2312
- Japanese systems: Shift-JIS
- Windows exports: Windows-1252

This cookbook demonstrates async loading of CSV files with custom encoding.

Run: `python cookbook/08_knowledge/readers/csv_reader_encoding_async.py`
"""

import asyncio
import tempfile
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.csv_reader import CSVReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def create_sample_csv():
    """Create a sample CSV with Latin-1 encoding (European data)."""
    # Customer data with European characters
    content = """CustomerID,Name,City,Country
1,Francois Muller,Strasbourg,France
2,Jose Garcia,Malaga,Spain
3,Hans Gruber,Munchen,Germany
4,Marie-Helene Dubois,Lyon,France
5,Bjorn Larsson,Goteborg,Sweden"""

    # Save with Latin-1 encoding
    temp_dir = Path(tempfile.mkdtemp())
    csv_path = temp_dir / "european_customers.csv"
    csv_path.write_bytes(content.encode("latin-1"))

    return csv_path


async def main():
    knowledge = Knowledge(
        vector_db=PgVector(table_name="csv_encoding_async", db_url=db_url),
    )

    # Create sample CSV file
    csv_path = create_sample_csv()
    print(f"Created sample CSV: {csv_path}")

    # Create reader with Latin-1 encoding
    reader = CSVReader(encoding="latin-1")

    print("\nLoading CSV with Latin-1 encoding (async)...")
    print("-" * 50)

    # Load using async method
    documents = await reader.async_read(csv_path)

    if documents:
        print(f"Loaded {len(documents)} document(s)")
        for doc in documents:
            print("\nDocument content preview:")
            print(doc.content[:200])
        await knowledge.ainsert(documents=documents)
    else:
        print("Failed to load (no documents returned)")

    # Clean up temp file
    csv_path.unlink()
    csv_path.parent.rmdir()

    # Query the knowledge base
    agent = Agent(
        knowledge=knowledge,
        search_knowledge=True,
    )

    print("\n" + "-" * 50)
    print("Querying knowledge base...")
    agent.print_response("List all customers from France", markdown=True)


if __name__ == "__main__":
    asyncio.run(main())
