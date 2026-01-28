from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.excel_reader import ExcelReader
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

reader = ExcelReader()

knowledge_base = Knowledge(
    vector_db=PgVector(
        table_name="excel_products_demo",
        db_url=db_url,
    ),
)

# Insert Excel file - ExcelReader uses openpyxl for .xlsx, xlrd for .xls
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
