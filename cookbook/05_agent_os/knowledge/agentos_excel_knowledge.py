"""AgentOS with Excel Knowledge - REST API for querying Excel data.

This example demonstrates using ExcelReader with AgentOS to:
- Load Excel files into a vector database
- Expose an agent via REST API
- Query Excel data through HTTP endpoints

Run with:
    uv run --no-sync python cookbook/05_agent_os/knowledge/agentos_excel_knowledge.py

Then test at: http://localhost:7777/
"""

from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.excel_reader import ExcelReader
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Excel knowledge base with row-level chunking (default)
excel_knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="agentos_excel_knowledge",
    ),
)

# Agent for querying Excel data
excel_agent = Agent(
    name="Excel Data Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
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

if __name__ == "__main__":
    # Determine paths relative to repo root
    repo_root = Path(__file__).parent.parent.parent.parent
    excel_samples = repo_root / "cookbook/07_knowledge/testing_resources/excel_samples"

    # Load sample Excel files
    if (excel_samples / "Employee Sample Data.xlsx").exists():
        print("Loading Employee Sample Data...")
        excel_knowledge.insert(
            path=str(excel_samples / "Employee Sample Data.xlsx"),
            reader=ExcelReader(),
            skip_if_exists=True,
        )

    if (excel_samples / "Financials Sample Data.xlsx").exists():
        print("Loading Financials Sample Data...")
        excel_knowledge.insert(
            path=str(excel_samples / "Financials Sample Data.xlsx"),
            reader=ExcelReader(),
            skip_if_exists=True,
        )

    print("\nStarting AgentOS server...")
    print("Test at: http://localhost:7777/")
    print("\nExample queries:")
    print("  - List employees in the IT department")
    print("  - What are the sales figures for Q1?")
    print("  - Who are the Technical Architects?")

    agent_os.serve(app="agentos_excel_knowledge:app", reload=True)
