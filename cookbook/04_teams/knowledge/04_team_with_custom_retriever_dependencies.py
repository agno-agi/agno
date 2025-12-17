"""
Example demonstrating Team with custom knowledge retriever and dependencies.

This cookbook shows how to:
1. Use a custom knowledge retriever with a Team
2. Pass dependencies to team.run()
3. Access dependencies in the custom retriever function

This demonstrates the fix for issue #5594 - custom retrievers can now access
runtime dependencies passed to team.run().

Setup:
    pip install agno qdrant-client openai

    # Start Qdrant locally
    docker run -p 6333:6333 qdrant/qdrant

    # Set your API key
    export OPENAI_API_KEY=your_api_key
"""

from typing import Optional

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.team import Team
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
# Initialize knowledge base
vector_db = PgVector(
    table_name="team-knowledge",
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    db_url=db_url,
)
knowledge = Knowledge(vector_db=vector_db)

# Add some sample content
knowledge.add_content(
    url="https://docs.agno.com/llms-full.txt",
)


def knowledge_retriever(
    query: str,
    team: Optional[Team] = None,
    num_documents: int = 5,
    run_context: Optional[RunContext] = None,
    **kwargs,
) -> Optional[list[dict]]:
    """
    Custom knowledge retriever for Team that uses runtime dependencies.

    Note: For Teams, the parameter is 'team' instead of 'agent'.

    Args:
        query: The search query string
        team: The team instance making the query
        num_documents: Number of documents to retrieve
        run_context: Runtime context containing dependencies and other context
        **kwargs: Additional keyword arguments

    Returns:
        List of retrieved documents or None if search fails
    """
    # Extract dependencies from run_context
    dependencies = run_context.dependencies if run_context else None

    if dependencies:
        print(f"[Team Retriever] Dependencies received: {list(dependencies.keys())}")

        # Access team-level context from dependencies
        project_id = dependencies.get("project_id")
        user_role = dependencies.get("role")
        team_context = dependencies.get("team_context")

        if project_id:
            print(f"[Team Retriever] Project ID: {project_id}")
            # You could filter by project_id in your vector DB here

        if user_role:
            print(f"[Team Retriever] User role: {user_role}")

        if team_context:
            print(f"[Team Retriever] Team context: {team_context}")
            # Use team context to customize search behavior
    else:
        print("[Team Retriever] No dependencies available")

    # Perform the actual search
    try:
        docs = knowledge.search(
            query=query,
            max_results=num_documents,
        )
        print(f"[Team Retriever] Found {len(docs)} documents")
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        print(f"[Team Retriever] Error: {e}")
        return []


# Create team members
researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o"),
    role="Research information from the knowledge base",
)

analyst = Agent(
    name="Analyst",
    model=OpenAIChat(id="gpt-4o"),
    role="Analyze and synthesize information",
)

# Create team with custom knowledge retriever
research_team = Team(
    name="Research Team",
    model=OpenAIChat(id="gpt-4o"),
    members=[researcher, analyst],
    knowledge=knowledge,
    knowledge_retriever=knowledge_retriever,
    search_knowledge=True,
    add_knowledge_to_context=True,
    instructions="Work together to research and analyze information. Always search the knowledge base first using the search_knowledge_base tool before answering.",
)


"""Demonstrate team with dependencies in knowledge retriever."""

print("=== Example 1: Team Without Dependencies ===\n")
response = research_team.run(
    "What are AI agents? Search the knowledge base for information.",
)
print(f"\nTeam Response: {response.content}\n")

print("\n=== Example 2: Team With Runtime Dependencies ===\n")
response = research_team.run(
    "What are AI agents? Search the knowledge base for information.",
    dependencies={
        "project_id": "project-123",
        "role": "researcher",
        "team_context": {
            "focus_area": "AI/ML",
            "priority": "high",
        },
    },
)
print(f"\nTeam Response: {response.content}\n")
