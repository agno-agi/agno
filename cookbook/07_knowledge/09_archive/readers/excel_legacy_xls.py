from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.excel_reader import ExcelReader
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# ExcelReader automatically uses xlrd for .xls files
# Date values are converted from Excel serial numbers to ISO format
# Boolean values are converted from 0/1 to True/False
reader = ExcelReader()

knowledge_base = Knowledge(
    vector_db=PgVector(
        table_name="excel_legacy_xls",
        db_url=db_url,
    ),
)

data_path = Path(__file__).parent.parent / "testing_resources" / "legacy_data.xls"

knowledge_base.insert(
    path=str(data_path),
    reader=reader,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge_base,
    search_knowledge=True,
    instructions=[
        "You are a data assistant for legacy Excel files.",
        "The workbook has two sheets: Sales Data and Inventory.",
        "Sales Data contains: Date, Product, Quantity, Price, Total.",
        "Inventory contains: Item, Available (True/False).",
        "Dates are in ISO format (YYYY-MM-DD).",
    ],
)

if __name__ == "__main__":
    print("=" * 60)
    print("Excel Legacy XLS - .xls Format Compatibility")
    print("=" * 60)

    print("\n--- Query 1: Sales records ---\n")
    agent.print_response(
        "What products were sold? Include the dates and quantities.",
        markdown=True,
        stream=True,
    )

    print("\n--- Query 2: Inventory status ---\n")
    agent.print_response(
        "Which items are currently available in inventory?",
        markdown=True,
        stream=True,
    )
