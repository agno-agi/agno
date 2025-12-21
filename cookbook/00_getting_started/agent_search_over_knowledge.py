"""
Agentic Search over Knowledge - Agent with a Knowledge Base
============================================================
This example shows how to give an agent a searchable knowledge base.
The agent can search through documents (PDFs, text, URLs) to answer questions.

Key concepts:
- Knowledge: A searchable collection of documents (PDFs, text, URLs)
- Agentic search: The agent decides when to search the knowledge base
- Hybrid search: Combines semantic similarity with keyword matching.

Example prompts to try:
- "What is Agno?"
- "What is the AgentOS?"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.google import Gemini
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.search import SearchType

# ============================================================================
# Storage Configuration
# ============================================================================
agent_db = SqliteDb(db_file="tmp/agents.db")

# ============================================================================
# Knowledge Configuration
# ============================================================================
knowledge = Knowledge(
    name="Agno Documentation",
    vector_db=ChromaDb(
        name="agno_docs",
        collection="agno_docs",
        path="tmp/chromadb",
        persistent_client=True,
        # Enable hybrid search - combines vector similarity with keyword matching using RRF
        search_type=SearchType.hybrid,
        # RRF (Reciprocal Rank Fusion) constant - controls ranking smoothness.
        # Higher values (e.g., 60) give more weight to lower-ranked results,
        # Lower values make top results more dominant. Default is 60 (per original RRF paper).
        hybrid_rrf_k=60,
        embedder=GeminiEmbedder(id="gemini-embedding-001"),
    ),
    # Return 5 results on query
    max_results=5,
    # Store metadata about the contents in the agent database, table_name="agno_knowledge"
    contents_db=agent_db,
)

# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are an expert on the Agno framework and building AI agents.

## Workflow

1. Search
   - For questions about Agno, always search your knowledge base first
   - Extract key concepts from the query to search effectively

2. Synthesize
   - Combine information from multiple search results
   - Prioritize official documentation over general knowledge

3. Present
   - Lead with a direct answer
   - Include code examples when helpful
   - Keep it practical and actionable

## Rules

- Always search knowledge before answering Agno questions
- If the answer isn't in the knowledge base, say so
- Include code snippets for implementation questions
- Be concise — developers want answers, not essays\
"""

# ============================================================================
# Create the Agent
# ============================================================================
agent_with_knowledge = Agent(
    name="Agent with Knowledge",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    knowledge=knowledge,
    search_knowledge=True,
    db=agent_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)

# ============================================================================
# Load Knowledge and Run the Agent
# ============================================================================
if __name__ == "__main__":
    # Load the introduction from the Agno documentation into the knowledge base
    # We're only loading 1 file to keep this example simple.
    knowledge.add_content(
        name="Agno Introduction", url="https://docs.agno.com/introduction.md"
    )

    agent_with_knowledge.print_response(
        "What is Agno?",
        stream=True,
    )

# ============================================================================
# More Examples
# ============================================================================
"""
Load your own knowledge:

1. From a URL
   knowledge.add_content(url="https://example.com/docs.pdf")

2. From a local file
   knowledge.add_content(path="path/to/document.pdf")

3. From text directly
   knowledge.add_content(text="Your content here...")

Hybrid search combines:
- Semantic search: Finds conceptually similar content
- Keyword search: Finds exact term matches
- Results fused using Reciprocal Rank Fusion (RRF)

The agent automatically searches when relevant (agentic search).
"""
