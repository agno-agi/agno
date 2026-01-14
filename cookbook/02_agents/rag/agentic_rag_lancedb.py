"""
1. Run: `pip install openai lancedb tantivy pypdf sqlalchemy agno` to install the dependencies
2. Run: `python cookbook/rag/04_agentic_rag_lancedb.py` to run the agent
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.lancedb import LanceDb, SearchType

knowledge = Knowledge(
    # Use LanceDB as the vector database and store embeddings in the `recipes` table
    vector_db=LanceDb(
        table_name="recipes",
        uri="tmp/lancedb",
        search_type=SearchType.vector,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    # Add a tool to search the knowledge base which enables agentic RAG.
    # This is enabled by default when `knowledge` is provided to the Agent.
    search_knowledge=True,
    markdown=True,
)
agent.print_response(
    "How do I make chicken and galangal in coconut milk soup", stream=True
)
