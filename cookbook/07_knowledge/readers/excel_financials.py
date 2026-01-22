from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.excel_reader import ExcelReader
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

reader = ExcelReader()

knowledge_base = Knowledge(
    vector_db=PgVector(
        table_name="excel_financials",
        db_url=db_url,
    ),
)

data_path = (
    Path(__file__).parent.parent
    / "testing_resources"
    / "excel_samples"
    / "Financials Sample Data.xlsx"
)

knowledge_base.insert(
    path=str(data_path),
    reader=reader,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge_base,
    search_knowledge=True,
    instructions=[
        "You are a financial analyst assistant.",
        "Use the knowledge base to answer questions about financial data.",
        "The data contains: Account (Sales, COGS, etc.), Business Unit, Currency, Year, Scenario (Actuals/Budget), and monthly figures (Jan-Dec).",
        "When asked about specific months, look for the monthly column values.",
        "Provide specific numbers when available.",
    ],
)

if __name__ == "__main__":
    print("=" * 60)
    print("Excel Financials - Time-Series Financial Data")
    print("=" * 60)

    print("\n--- Query 1: Sales figures ---\n")
    agent.print_response(
        "What were the Sales figures for the Software business unit? Show the monthly breakdown if available.",
        markdown=True,
        stream=True,
    )

    print("\n--- Query 2: Budget vs Actuals ---\n")
    agent.print_response(
        "Compare Budget vs Actuals scenarios. What differences do you see?",
        markdown=True,
        stream=True,
    )

    print("\n--- Query 3: Business unit comparison ---\n")
    agent.print_response(
        "Which business units have Cost of Goods Sold (COGS) data? List them with their figures.",
        markdown=True,
        stream=True,
    )
