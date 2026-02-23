"""
Knowledge Tools: Think, Search, Analyze
=========================================
KnowledgeTools provides a richer set of tools for knowledge interaction
beyond basic search:

- think: Agent reasons about the query before searching
- search: Standard knowledge base search
- analyze: Deep analysis of search results

This gives agents more sophisticated reasoning over knowledge.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.tools.knowledge import KnowledgeTools
from agno.vectordb.pgvector import PgVector, SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="knowledge_tools_demo",
        db_url=db_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

knowledge_tools = KnowledgeTools(
    knowledge=knowledge,
    enable_think=True,
    enable_search=True,
    enable_analyze=True,
    add_few_shot=True,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[knowledge_tools],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    knowledge.insert(url="https://docs.agno.com/llms-full.txt")

    print("\n" + "=" * 60)
    print("KnowledgeTools: think + search + analyze")
    print("=" * 60 + "\n")

    agent.print_response(
        "How do I build a team of agents in Agno?",
        stream=True,
    )
