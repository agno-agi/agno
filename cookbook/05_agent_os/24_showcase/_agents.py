"""
Create the Showcase Agents
==========================

Define the shared PostgreSQL database, pgvector-backed Agno documentation
knowledge, a focused RAG assistant, and a current web-and-finance researcher.

Prerequisites: Postgres on port 5532, OPENAI_API_KEY, and ANTHROPIC_API_KEY
Run: .venvs/demo/bin/python -m cookbook.05_agent_os.24_showcase.demo
Try: ask Agno Assist about AgentOS, or ask Sage for sourced market context
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Create Showcase Storage and Knowledge
# ---------------------------------------------------------------------------

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
AGNO_DOCS_URL = "https://docs.agno.com/agent-os/introduction.md"

showcase_db = PostgresDb(
    id="agent-os-showcase-db",
    db_url=DB_URL,
    session_table="agent_os_showcase_sessions",
    knowledge_table="agent_os_showcase_knowledge",
    eval_table="agent_os_showcase_evals",
    traces_table="agent_os_showcase_traces",
    spans_table="agent_os_showcase_spans",
)

agno_docs = Knowledge(
    name="Agno Documentation",
    description="Agno documentation used by the showcase RAG assistant.",
    contents_db=showcase_db,
    vector_db=PgVector(
        db_url=DB_URL,
        table_name="agent_os_showcase_documents",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=5,
)

# ---------------------------------------------------------------------------
# Create Showcase Agents
# ---------------------------------------------------------------------------

agno_assist = Agent(
    id="agno-assist",
    name="Agno Assist",
    role="Answer questions about Agno from the indexed documentation.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=showcase_db,
    knowledge=agno_docs,
    instructions=[
        "Search the Agno documentation before answering.",
        "Base framework claims on retrieved documentation.",
        "Say when the indexed documentation does not answer the question.",
        "Keep answers concise and include the relevant documentation URL.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

sage = Agent(
    id="sage",
    name="Sage",
    role="Research current market questions with web and financial data.",
    model=Claude(id="claude-sonnet-4-6"),
    db=showcase_db,
    tools=[
        WebSearchTools(
            enable_search=True,
            enable_news=True,
            fixed_max_results=5,
            timeout=20,
        ),
        YFinanceTools(
            enable_stock_price=True,
            enable_company_info=True,
            enable_stock_fundamentals=True,
            enable_analyst_recommendations=True,
            enable_company_news=True,
        ),
    ],
    instructions=[
        "Use YFinanceTools for prices, fundamentals, and analyst data.",
        "Use WebSearchTools for current context and claims outside market data.",
        "Cite web sources and label market data with its retrieval date.",
        "Separate observed facts from your interpretation.",
        "Never claim to have used a tool unless its result is in the run.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run through the Showcase App
# ---------------------------------------------------------------------------

# These shared objects are imported by _teams.py and demo.py so all showcase
# components use one database and one knowledge instance.
