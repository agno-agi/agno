"""
Agentos Excel Analyst
=====================

Demonstrates agentos excel analyst.
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.excel_reader import ExcelReader
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)

excel_knowledge = Knowledge(
    name="Excel Products",
    contents_db=db,  # Required for UI to show knowledge
    vector_db=PgVector(
        db_url=db_url,
        table_name="agentos_excel_knowledge",
    ),
)

excel_agent = Agent(
    name="Excel Data Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,  # For session storage
    knowledge=excel_knowledge,
    search_knowledge=True,
    markdown=True,
    instructions=[
        "You are a data analyst assistant with access to Excel spreadsheet data.",
        "Search the knowledge base to answer questions about the data.",
        "Provide specific numbers and details when available.",
    ],
)

# Create AgentOS app
agent_os = AgentOS(
    description="Excel Knowledge API - Query Excel data via REST",
    agents=[excel_agent],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    repo_root = Path(__file__).parent.parent.parent.parent
    sample_file = (
        repo_root / "cookbook/07_knowledge/testing_resources/sample_products.xlsx"
    )

    if sample_file.exists():
        print("Loading sample products data...")
        excel_knowledge.insert(
            path=str(sample_file),
            reader=ExcelReader(),
            skip_if_exists=True,
        )

    print("\nStarting AgentOS server...")
    print("Test at: http://localhost:7777/")
    print("\nExample queries:")
    print("  - What electronics products are in stock?")
    print("  - What is the price of the Bluetooth speaker?")

    agent_os.serve(app="agentos_excel_analyst:app", reload=True)
