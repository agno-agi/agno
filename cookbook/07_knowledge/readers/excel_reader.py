"""
Excel Reader Example

Demonstrates reading Excel (.xlsx/.xls) files with the Knowledge system.
CSVReader automatically handles Excel files - each sheet becomes a separate document
with sheet metadata (sheet_name, sheet_index).

Features demonstrated:
- Multi-sheet workbook handling
- Various data types (strings, numbers, booleans, dates)
- Sheet metadata preservation
- Integration with Knowledge and Agent
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.csv_reader import CSVReader
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# CSVReader handles Excel files automatically (.xlsx and .xls)
reader = CSVReader()

knowledge_base = Knowledge(
    vector_db=PgVector(
        table_name="excel_products_demo",
        db_url=db_url,
    ),
)

# Insert Excel file - the reader detects .xlsx extension and uses openpyxl
knowledge_base.insert(
    path="cookbook/07_knowledge/testing_resources/sample_products.xlsx",
    reader=reader,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge_base,
    search_knowledge=True,
    instructions=[
        "You are a product catalog assistant.",
        "Use the knowledge base to answer questions about products.",
        "The data comes from an Excel workbook with Products and Categories sheets.",
    ],
)

if __name__ == "__main__":
    agent.print_response(
        "What electronics products are currently in stock? Include their prices.",
        markdown=True,
        stream=True,
    )
    agent.print_response(
        "What is the price of the Bluetooth speaker?",
        markdown=True,
        stream=True,
    )
