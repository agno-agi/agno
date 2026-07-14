"""
LLMs.txt Tools with Knowledge Base
=============================

Demonstrates loading all documentation from an llms.txt file into a knowledge base
for retrieval-augmented generation (RAG).

The agent reads the llms.txt index, fetches all linked documentation pages,
and stores them in a PgVector knowledge base for semantic search.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.tools.llms_txt import LLMsTxtTools
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Setup Knowledge Base
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="llms_txt_docs",
        db_url=db_url,
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    knowledge=knowledge,
    search_knowledge=True,
    tools=[LLMsTxtTools(knowledge=knowledge, max_urls=20)],
    instructions=[
        "You can load documentation from llms.txt files into your knowledge base.",
        "When asked about a project, first load its llms.txt into the knowledge base, then answer questions.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Load the documentation from https://docs.agno.com/llms.txt into the knowledge base, "
        "then tell me how to create an agent with Agno",
        markdown=True,
        stream=True,
    )
