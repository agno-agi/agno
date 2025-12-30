"""
This example demonstrates how multiple specialized agents coordinate to provide
comprehensive RAG responses using distributed PostgreSQL vector databases with
pgvector for scalable, production-ready retrieval.

Team Composition:
- Vector Retriever: Specialized in vector similarity search using pgvector
- Hybrid Searcher: Combines vector and text search for comprehensive results
- Data Validator: Validates retrieved data quality and relevance
- Response Composer: Composes final responses with proper source attribution

Setup:
1. Run: `./cookbook/run_pgvector.sh` to start a postgres container with pgvector
2. Run: `pip install openai sqlalchemy 'psycopg[binary]' pgvector agno`
3. Run this script to see distributed PgVector RAG in action
"""

import asyncio  # noqa: F401

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.vectordb.pgvector import PgVector, SearchType

# Database connection URL
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Vector-focused knowledge base for similarity search
vector_knowledge = Knowledge(
    vector_db=PgVector(
        table_name="recipes_vector",
        db_url=db_url,
        search_type=SearchType.vector,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Hybrid knowledge base for comprehensive search
hybrid_knowledge = Knowledge(
    vector_db=PgVector(
        table_name="recipes_hybrid",
        db_url=db_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Vector Retriever Agent - Specialized in vector similarity search
vector_retriever = Agent(
    name="Vector Retriever",
    model=OpenAIChat(id="o3-mini"),
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

# Hybrid Searcher Agent - Specialized in hybrid search
hybrid_searcher = Agent(
    name="Hybrid Searcher",
    model=OpenAIChat(id="o3-mini"),
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

# Data Validator Agent - Specialized in data quality validation
data_validator = Agent(
    name="Data Validator",
    model=OpenAIChat(id="o3-mini"),
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

# Response Composer Agent - Specialized in response composition
response_composer = Agent(
    name="Response Composer",
    model=OpenAIChat(id="o3-mini"),
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

# Create distributed PgVector RAG team
distributed_pgvector_team = Team(
    name="Distributed PgVector RAG Team",
    model=OpenAIChat(id="o3-mini"),
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


async def async_pgvector_rag_demo():
    """Demonstrate async distributed PgVector RAG processing."""
    print("🐘 Async Distributed PgVector RAG Demo")
    print("=" * 40)

    query = "How do I make chicken and galangal in coconut milk soup? What are the key ingredients and techniques?"

    try:
        # Add content to knowledge bases
        await vector_knowledge.add_contents_async(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        await hybrid_knowledge.add_contents_async(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        # Run async distributed PgVector RAG
        await distributed_pgvector_team.aprint_response(input=query)
    except Exception as e:
        print(f"❌ Error: {e}")
        print("💡 Make sure PostgreSQL with pgvector is running!")
        print("   Run: ./cookbook/run_pgvector.sh")


def sync_pgvector_rag_demo():
    """Demonstrate sync distributed PgVector RAG processing."""
    print("🐘 Distributed PgVector RAG Demo")
    print("=" * 35)

    query = "How do I make chicken and galangal in coconut milk soup? What are the key ingredients and techniques?"

    try:
        # Add content to knowledge bases
        vector_knowledge.add_contents(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        hybrid_knowledge.add_contents(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        # Run distributed PgVector RAG
        distributed_pgvector_team.print_response(input=query)
    except Exception as e:
        print(f"❌ Error: {e}")
        print("💡 Make sure PostgreSQL with pgvector is running!")
        print("   Run: ./cookbook/run_pgvector.sh")


def complex_query_demo():
    """Demonstrate distributed RAG for complex culinary queries."""
    print("👨‍🍳 Complex Culinary Query with Distributed PgVector RAG")
    print("=" * 60)

    query = """I'm planning a Thai dinner party for 8 people. Can you help me plan a complete menu?
    I need appetizers, main courses, and desserts. Please include:
    - Preparation timeline
    - Shopping list
    - Cooking techniques for each dish
    - Any dietary considerations or alternatives"""

    try:
        # Add content to knowledge bases
        vector_knowledge.add_contents(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )
        hybrid_knowledge.add_contents(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )

        distributed_pgvector_team.print_response(input=query)
    except Exception as e:
        print(f"❌ Error: {e}")
        print("💡 Make sure PostgreSQL with pgvector is running!")
        print("   Run: ./cookbook/run_pgvector.sh")


if __name__ == "__main__":
    # Choose which demo to run

    # asyncio.run(async_pgvector_rag_demo())

    # complex_query_demo()

    sync_pgvector_rag_demo()
