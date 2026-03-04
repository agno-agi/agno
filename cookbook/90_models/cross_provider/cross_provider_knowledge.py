"""
Cross-Provider Knowledge: RAG Across Provider Switches
=======================================================

Demonstrates knowledge/RAG queries persisted across provider switches.
All three providers query the same LanceDB knowledge base within a
single session.

Flow:
  1. Load sample documents into LanceDB knowledge base
  2. Gemini searches knowledge ("What is agno?")
  3. OpenAI asks a follow-up using history + knowledge
  4. Claude asks a different knowledge question

Requires: GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.knowledge import Knowledge
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.vectordb.lancedb import LanceDb, SearchType

vector_db = LanceDb(
    uri="tmp/lancedb",
    table_name="cross_provider_knowledge",
    search_type=SearchType.hybrid,
)

knowledge = Knowledge(
    name="Cross-Provider Docs",
    vector_db=vector_db,
)

agent_db = SqliteDb(db_file="tmp/cross_provider.db", session_table="knowledge_sessions")

session_id = "cross-provider-knowledge"
instructions = """\
You are a helpful assistant with access to a knowledge base. Always search the
knowledge base before answering. Cite specific details from the documents.\
"""

gemini_agent = Agent(
    name="Knowledge Agent (Gemini)",
    model=Gemini(id="gemini-2.0-flash"),
    instructions=instructions,
    knowledge=knowledge,
    search_knowledge=True,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

openai_agent = Agent(
    name="Knowledge Agent (OpenAI)",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=instructions,
    knowledge=knowledge,
    search_knowledge=True,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

claude_agent = Agent(
    name="Knowledge Agent (Claude)",
    model=Claude(id="claude-sonnet-4-20250514"),
    instructions=instructions,
    knowledge=knowledge,
    search_knowledge=True,
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

SAMPLE_DOCS = [
    {
        "name": "Agno Overview",
        "text_content": (
            "Agno is a lightweight framework for building multi-modal agents. "
            "It supports tool use, knowledge bases, memory, and structured outputs. "
            "Agents can switch between different LLM providers like OpenAI, Anthropic, "
            "and Google while sharing the same session and conversation history. "
            "Agno is designed for production use with both sync and async support."
        ),
        "metadata": {"topic": "overview", "version": "1.0"},
    },
    {
        "name": "Agno Knowledge System",
        "text_content": (
            "The Agno knowledge system uses vector databases to store and retrieve "
            "documents. Supported vector databases include LanceDB, PgVector, Pinecone, "
            "and Qdrant. Documents are automatically chunked and embedded using "
            "configurable embedders. The knowledge base supports hybrid search combining "
            "semantic similarity with keyword matching for better retrieval accuracy."
        ),
        "metadata": {"topic": "knowledge", "version": "1.0"},
    },
    {
        "name": "Agno Cross-Provider",
        "text_content": (
            "Cross-provider interoperability allows agents to switch LLM providers "
            "mid-session. Tool call results from one provider are normalized into a "
            "canonical format before being formatted for the next provider. This enables "
            "workflows like: Gemini fetches data, Claude analyzes it, and OpenAI "
            "summarizes the findings, all within a single session."
        ),
        "metadata": {"topic": "cross-provider", "version": "1.0"},
    },
]

if __name__ == "__main__":
    print("Loading documents into knowledge base...")
    for doc in SAMPLE_DOCS:
        knowledge.insert(
            name=doc["name"],
            text_content=doc["text_content"],
            metadata=doc["metadata"],
        )
    print("Knowledge base loaded.\n")

    print("=" * 60)
    print("Turn 1: Gemini searches knowledge")
    print("=" * 60)
    gemini_agent.print_response(
        "What is Agno and what are its main features?",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 2: OpenAI asks follow-up using history + knowledge")
    print("=" * 60)
    openai_agent.print_response(
        "What vector databases does the knowledge system support? How does hybrid search work?",
        session_id=session_id,
        stream=True,
    )

    print("\n")
    print("=" * 60)
    print("Turn 3: Claude asks about cross-provider")
    print("=" * 60)
    claude_agent.print_response(
        "How does cross-provider interoperability work? Give a concrete workflow example.",
        session_id=session_id,
        stream=True,
    )
