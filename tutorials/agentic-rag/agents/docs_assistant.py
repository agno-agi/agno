"""
Agno Docs Assistant

Demonstrates two key RAG capabilities:

1. SEARCH QUALITY (Problem 1)
   - Vector DB: PgVector with hybrid search (semantic + keyword)
   - Reader: TextReader for parsing documents
   - Chunker: RecursiveChunking for hierarchical text splitting
   - Embedder: OpenAIEmbedder for vector generation

2. ACCESS CONTROL (Problem 2)
   - Preselected filters: Hardcode filters per query
   - Agentic filters: Agent infers filters from query context
   - Filter expressions: Complex logic with AND/OR/NOT/EQ/IN
"""

from textwrap import dedent

from dotenv import load_dotenv
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.reader.text_reader import TextReader
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType

from db.session import db_url

load_dotenv()

# =============================================================================
# Documents with metadata for filtering
# =============================================================================

AGNO_DOCS = [
    {
        "url": "https://docs.agno.com/llms-full.txt",
        "metadata": {"category": "llms", "doc_type": "reference"},
    },
]


# =============================================================================
# Problem 1: Search Quality
# - Hybrid search (semantic + keyword)
# - Recursive chunking (hierarchical splitting)
# - Quality embeddings
# =============================================================================

def get_knowledge() -> Knowledge:
    """Create knowledge base with hybrid search and quality embeddings."""
    return Knowledge(
        vector_db=PgVector(
            table_name="agno_docs",
            db_url=db_url,
            # Hybrid = semantic similarity + keyword matching
            search_type=SearchType.hybrid,
            # Quality embeddings for better retrieval
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )


def load_knowledge(knowledge: Knowledge) -> None:
    """Load documents with recursive chunking and metadata."""
    # Recursive chunking splits text hierarchically for better context
    reader = TextReader(
        chunking_strategy=RecursiveChunking()
    )

    for doc in AGNO_DOCS:
        knowledge.add_content(
            url=doc["url"],
            reader=reader,
            # Metadata enables filtering (Problem 2)
            metadata=doc["metadata"],
        )


# =============================================================================
# Problem 2: Access Control
# - Preselected filters: knowledge_filters={"category": "llms"}
# - Agentic filters: enable_agentic_knowledge_filters=True
# - Filter expressions: AND, OR, NOT, EQ, IN
# =============================================================================

def get_docs_assistant(
    model_id: str = "gpt-4o-mini",
    debug_mode: bool = False,
    enable_agentic_filters: bool = False,
    knowledge: Knowledge | None = None,
) -> Agent:
    """Create agent with optional agentic filters."""
    if knowledge is None:
        knowledge = get_knowledge()

    return Agent(
        id="docs-assistant",
        name="Agno Docs Assistant",
        model=OpenAIChat(id=model_id),
        knowledge=knowledge,
        search_knowledge=True,
        # Agentic filters - agent picks filters based on query context
        enable_agentic_knowledge_filters=enable_agentic_filters,
        description="You are a helpful assistant that answers questions about Agno.",
        instructions=dedent("""\
            Always search the knowledge base before answering.
            If you can't find relevant information, say so clearly.
            Include code examples when available.
        """),
        markdown=True,
        debug_mode=debug_mode,
    )


# =============================================================================
# Examples
# =============================================================================

if __name__ == "__main__":
    from agno.filters import AND, EQ

    # Load docs
    knowledge = get_knowledge()
    load_knowledge(knowledge)
    agent = get_docs_assistant()

    # -------------------------------------------------------------------------
    # Problem 1: Search Quality
    # Hybrid search + recursive chunking = better retrieval
    # -------------------------------------------------------------------------
    print("=" * 60)
    print("PROBLEM 1: Search Quality")
    print("Hybrid search finds semantically similar content")
    print("=" * 60)
    agent.print_response("How do I create an agent in Agno?", stream=True)

    # -------------------------------------------------------------------------
    # Problem 2: Access Control - Preselected Filters
    # Hardcode which docs to search
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("PROBLEM 2a: Preselected Filters")
    print("Only search docs where category=llms")
    print("=" * 60)
    agent.print_response(
        "What models are available?",
        knowledge_filters={"category": "llms"},
        stream=True,
    )

    # -------------------------------------------------------------------------
    # Problem 2: Access Control - Agentic Filters
    # Agent infers filters from query context
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("PROBLEM 2b: Agentic Filters")
    print("Agent automatically infers filters from query")
    print("=" * 60)
    agent_agentic = get_docs_assistant(enable_agentic_filters=True)
    agent_agentic.print_response("Tell me about LLM providers", stream=True)

    # -------------------------------------------------------------------------
    # Problem 2: Access Control - Filter Expressions
    # Complex logic with AND/OR/NOT/EQ/IN
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("PROBLEM 2c: Filter Expressions")
    print("Complex filter: category=llms AND doc_type=reference")
    print("=" * 60)
    agent.print_response(
        "What documentation is available?",
        knowledge_filters=[
            AND(
                EQ("category", "llms"),
                EQ("doc_type", "reference")
            )
        ],
        stream=True,
    )

    # More filter examples:
    # OR:  OR(EQ("category", "llms"), EQ("category", "tools"))
    # IN:  IN("category", ["llms", "tools", "agents"])
    # NOT: NOT(EQ("doc_type", "deprecated"))
