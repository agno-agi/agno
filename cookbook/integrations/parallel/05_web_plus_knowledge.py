"""
Web + Knowledge - Live Search Meets Your Own Documents
======================================================

Real agents need two kinds of information: what is in your own documents, and
what is happening on the web right now. This example gives one agent both:

- Agno Knowledge (a local Chroma vector store) for internal or static docs
- Parallel Search for fresh, live information from the web

The agent decides which to use: it searches its knowledge base for grounded
facts and reaches for Parallel when the question needs current data.

Prerequisites:
- pip install parallel-web chromadb
- export PARALLEL_API_KEY=<your-api-key>
- export OPENAI_API_KEY=<your-api-key>   (model + embeddings)
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup - local knowledge base (embedded, no server needed)
# ---------------------------------------------------------------------------
knowledge = Knowledge(
    vector_db=ChromaDb(
        collection="company_knowledge",
        path="tmp/chromadb",
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
# search_knowledge=True gives the agent a knowledge-search tool; ParallelTools
# gives it live web search. It chooses per question.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    knowledge=knowledge,
    search_knowledge=True,
    tools=[ParallelTools()],
    markdown=True,
    instructions=[
        "Answer from your knowledge base when the facts are internal or static.",
        "Use Parallel web search when the question needs current information.",
        "Tell the user which source you used: knowledge base or live web.",
    ],
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Load a document into the knowledge base (stands in for internal docs).
    knowledge.insert(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")

    # Internal question -> knowledge base.
    agent.print_response(
        "From our documents, how do I make Tom Kha Gai?",
        stream=True,
    )

    # Live question -> Parallel web search.
    agent.print_response(
        "What is the latest news on AI agent frameworks this week?",
        stream=True,
    )
