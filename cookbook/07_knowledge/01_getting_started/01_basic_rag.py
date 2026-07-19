"""
Basic RAG: Context Injection
=============================
The simplest way to give an agent access to documents. Content is automatically
retrieved and injected into the system prompt before the agent responds.

This pattern works well for simple Q&A over documents. The agent doesn't need
to decide whether to search - it always gets relevant context.

Steps:
1. Create a Knowledge base with a vector database
2. Load a document
3. Create an Agent with add_knowledge_to_context=True
4. Ask questions - context is injected automatically

See also: 02_agentic_rag.py for agent-driven search decisions.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="basic_rag",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Traditional RAG: context is fetched and injected into the prompt automatically.
# The agent doesn't get a search tool - it just sees the relevant context.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    add_knowledge_to_context=True,
    search_knowledge=False,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        await knowledge.ainsert(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )

        print("\n" + "=" * 60)
        print("Basic RAG: Context injected into prompt automatically")
        print("=" * 60 + "\n")

        agent.print_response(
            "How do I make chicken and galangal in coconut milk soup",
            stream=True,
        )

    asyncio.run(main())
