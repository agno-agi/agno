"""
Example demonstrating custom knowledge retriever with runtime dependencies.

This cookbook shows how to access dependencies passed at runtime (e.g., via agent.run(dependencies={...}))
in a custom knowledge retriever function.

Key points:
1. Add 'run_context' parameter to your retriever function signature
2. Dependencies are automatically passed from run_context when available
3. Use dependencies to customize retrieval behavior based on user context
"""

from typing import Optional

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
# Initialize knowledge base
knowledge = Knowledge(
    vector_db=PgVector(
        table_name="dependencies_knowledge",
        db_url=db_url,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Add some sample content
knowledge.add_content(
    url="https://docs.agno.com/llms-full.txt",
)


def knowledge_retriever(
    query: str,
    agent: Optional[Agent] = None,
    num_documents: int = 5,
    run_context: Optional[RunContext] = None,
    **kwargs,
) -> Optional[list[dict]]:
    """
    Custom knowledge retriever that uses runtime dependencies.

    Args:
        query: The search query string
        agent: The agent instance making the query
        num_documents: Number of documents to retrieve (default: 5)
        run_context: Runtime context containing dependencies and other context
        **kwargs: Additional keyword arguments

    Returns:
        List of retrieved documents or None if search fails
    """
    # Extract dependencies from run_context
    dependencies = run_context.dependencies if run_context else None

    print("\n=== Knowledge Retriever Called ===")
    print(f"Query: {query}")
    print(f"Dependencies available: {dependencies is not None}")

    if dependencies:
        print(f"Dependencies keys: {list(dependencies.keys())}")

        # Example: Use user role from dependencies to filter results
        user_role = dependencies.get("role", "user")
        print(f"User role: {user_role}")

        # Example: Use user preferences to customize search
        if "preferences" in dependencies:
            print(f"User preferences: {dependencies['preferences']}")

    # Perform the actual search
    try:
        docs = knowledge.search(
            query=query,
            max_results=num_documents,
        )
        print(f"Found {len(docs)} documents")
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        print(f"Error during knowledge retrieval: {e}")
        return []


agent = Agent(
    name="KnowledgeAgent",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    knowledge_retriever=knowledge_retriever,
    search_knowledge=True,
    instructions="Search the knowledge base for information. Use the search_knowledge_base tool when needed.",
)

print("=== Example 1: Without Dependencies ===\n")
agent.print_response(
    "What are AI agents?",
    markdown=True,
)

print("\n\n=== Example 2: With Runtime Dependencies ===\n")
agent.print_response(
    "What are AI agents?",
    markdown=True,
    dependencies={
        "role": "admin",
        "preferences": ["AI", "Machine Learning"],
    },
)
