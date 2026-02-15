"""
Distributed RAG With PgVector
=============================

Demonstrates distributed team-based RAG using PostgreSQL + pgvector.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.vectordb.pgvector import PgVector, SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

vector_knowledge = Knowledge(
    vector_db=PgVector(
        table_name="recipes_vector",
        db_url=db_url,
        search_type=SearchType.vector,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

hybrid_knowledge = Knowledge(
    vector_db=PgVector(
        table_name="recipes_hybrid",
        db_url=db_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
vector_retriever = Agent(
    name="Vector Retriever",
    model=OpenAIResponses(id="gpt-5-mini"),
    role="Retrieve information using vector similarity search in PostgreSQL",
    knowledge=vector_knowledge,
    search_knowledge=True,
    instructions=[
        "Use vector similarity search to find semantically related content.",
        "Focus on finding information that matches the semantic meaning of queries.",
        "Leverage pgvector's efficient similarity search capabilities.",
        "Retrieve content that has high semantic relevance to the user's query.",
    ],
    markdown=True,
)

hybrid_searcher = Agent(
    name="Hybrid Searcher",
    model=OpenAIResponses(id="gpt-5-mini"),
    role="Perform hybrid search combining vector and text search",
    knowledge=hybrid_knowledge,
    search_knowledge=True,
    instructions=[
        "Combine vector similarity and text search for comprehensive results.",
        "Find information that matches both semantic and lexical criteria.",
        "Use PostgreSQL's hybrid search capabilities for best coverage.",
        "Ensure retrieval of both conceptually and textually relevant content.",
    ],
    markdown=True,
)

data_validator = Agent(
    name="Data Validator",
    model=OpenAIResponses(id="gpt-5-mini"),
    role="Validate retrieved data quality and relevance",
    instructions=[
        "Assess the quality and relevance of retrieved information.",
        "Check for consistency across different search results.",
        "Identify the most reliable and accurate information.",
        "Filter out any irrelevant or low-quality content.",
        "Ensure data integrity and relevance to the user's query.",
    ],
    markdown=True,
)

response_composer = Agent(
    name="Response Composer",
    model=OpenAIResponses(id="gpt-5-mini"),
    role="Compose comprehensive responses with proper source attribution",
    instructions=[
        "Combine validated information from all team members.",
        "Create well-structured, comprehensive responses.",
        "Include proper source attribution and data provenance.",
        "Ensure clarity and coherence in the final response.",
        "Format responses for optimal user experience.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
distributed_pgvector_team = Team(
    name="Distributed PgVector RAG Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[vector_retriever, hybrid_searcher, data_validator, response_composer],
    instructions=[
        "Work together to provide comprehensive RAG responses using PostgreSQL pgvector.",
        "Vector Retriever: First perform vector similarity search.",
        "Hybrid Searcher: Then perform hybrid search for comprehensive coverage.",
        "Data Validator: Validate and filter the retrieved information quality.",
        "Response Composer: Compose the final response with proper attribution.",
        "Leverage PostgreSQL's scalability and pgvector's performance.",
        "Ensure enterprise-grade reliability and accuracy.",
    ],
    show_members_responses=True,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
async def async_pgvector_rag_demo() -> None:
    """Demonstrate async distributed PgVector RAG processing."""
    print("Async Distributed PgVector RAG Demo")
    print("=" * 40)

    query = "How do I make chicken and galangal in coconut milk soup? What are the key ingredients and techniques?"

    try:
        await vector_knowledge.ainsert_many(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        await hybrid_knowledge.ainsert_many(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        await distributed_pgvector_team.aprint_response(input=query)
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure PostgreSQL with pgvector is running!")
        print("   Run: ./cookbook/run_pgvector.sh")


def sync_pgvector_rag_demo() -> None:
    """Demonstrate sync distributed PgVector RAG processing."""
    print("Distributed PgVector RAG Demo")
    print("=" * 35)

    query = "How do I make chicken and galangal in coconut milk soup? What are the key ingredients and techniques?"

    try:
        vector_knowledge.insert_many(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        hybrid_knowledge.insert_many(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        distributed_pgvector_team.print_response(input=query)
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure PostgreSQL with pgvector is running!")
        print("   Run: ./cookbook/run_pgvector.sh")


def complex_query_demo() -> None:
    """Demonstrate distributed RAG for complex culinary queries."""
    print("Complex Culinary Query with Distributed PgVector RAG")
    print("=" * 60)

    query = """I'm planning a Thai dinner party for 8 people. Can you help me plan a complete menu?
    I need appetizers, main courses, and desserts. Please include:
    - Preparation timeline
    - Shopping list
    - Cooking techniques for each dish
    - Any dietary considerations or alternatives"""

    try:
        vector_knowledge.insert_many(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        hybrid_knowledge.insert_many(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )

        distributed_pgvector_team.print_response(input=query)
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure PostgreSQL with pgvector is running!")
        print("   Run: ./cookbook/run_pgvector.sh")


if __name__ == "__main__":
    # Choose which demo to run

    # asyncio.run(async_pgvector_rag_demo())

    # complex_query_demo()

    sync_pgvector_rag_demo()
