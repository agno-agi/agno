"""
This example demonstrates how multiple agents coordinate to perform distributed
search using Infinity reranker for high-performance ranking across team members.

Team Composition:
- Primary Searcher: Performs initial broad search with infinity reranking
- Secondary Searcher: Performs targeted search on specific topics
- Cross-Reference Validator: Validates information across different sources
- Result Synthesizer: Combines and ranks all results for final response

Setup:
1. Install dependencies: `pip install agno anthropic infinity-client lancedb`
2. Set up Infinity Server:
   ```bash
   pip install "infinity-emb[all]"
   infinity_emb v2 --model-id BAAI/bge-reranker-base --port 7997
   ```
3. Export ANTHROPIC_API_KEY
4. Run this script
"""

from agno.agent import Agent
from agno.knowledge.embedder.cohere import CohereEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.infinity import InfinityReranker
from agno.models.anthropic import Claude
from agno.team.team import Team
from agno.vectordb.lancedb import LanceDb, SearchType

# Knowledge base with Infinity reranker for high performance
knowledge_primary = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs_primary",
        search_type=SearchType.hybrid,
        embedder=CohereEmbedder(id="embed-v4.0"),
        reranker=InfinityReranker(
            base_url="http://localhost:7997/rerank", model="BAAI/bge-reranker-base"
        ),
    ),
)

# Secondary knowledge base for targeted search
knowledge_secondary = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs_secondary",
        search_type=SearchType.hybrid,
        embedder=CohereEmbedder(id="embed-v4.0"),
        reranker=InfinityReranker(
            base_url="http://localhost:7997/rerank", model="BAAI/bge-reranker-base"
        ),
    ),
)

# Primary Searcher Agent - Broad search with infinity reranking
primary_searcher = Agent(
    name="Primary Searcher",
    model=Claude(id="claude-3-7-sonnet-latest"),
    role="Perform comprehensive primary search with high-performance reranking",
    knowledge=knowledge_primary,
    search_knowledge=True,
    instructions=[
        "Conduct broad, comprehensive searches across the knowledge base.",
        "Use the infinity reranker to ensure high-quality result ranking.",
        "Focus on capturing the most relevant information first.",
        "Provide detailed context and multiple perspectives on topics.",
    ],
    markdown=True,
)

# Secondary Searcher Agent - Targeted and specialized search
secondary_searcher = Agent(
    name="Secondary Searcher",
    model=Claude(id="claude-3-7-sonnet-latest"),
    role="Perform targeted searches on specific topics and edge cases",
    knowledge=knowledge_secondary,
    search_knowledge=True,
    instructions=[
        "Perform targeted searches on specific aspects of the query.",
        "Look for edge cases, technical details, and specialized information.",
        "Use infinity reranking to find the most precise matches.",
        "Focus on details that complement the primary search results.",
    ],
    markdown=True,
)

# Cross-Reference Validator Agent - Validates across sources
cross_reference_validator = Agent(
    name="Cross-Reference Validator",
    model=Claude(id="claude-3-7-sonnet-latest"),
    role="Validate information consistency across different search results",
    instructions=[
        "Compare and validate information from both searchers.",
        "Identify consistencies and discrepancies in the results.",
        "Highlight areas where information aligns or conflicts.",
        "Assess the reliability of different information sources.",
    ],
    markdown=True,
)

# Result Synthesizer Agent - Combines and ranks all findings
result_synthesizer = Agent(
    name="Result Synthesizer",
    model=Claude(id="claude-3-7-sonnet-latest"),
    role="Synthesize and rank all search results into comprehensive response",
    instructions=[
        "Combine results from all team members into a unified response.",
        "Rank information based on relevance and reliability.",
        "Ensure comprehensive coverage of the query topic.",
        "Present results with clear source attribution and confidence levels.",
    ],
    markdown=True,
)

# Create distributed search team
distributed_search_team = Team(
    name="Distributed Search Team with Infinity Reranker",
    model=Claude(id="claude-3-7-sonnet-latest"),
    members=[
        primary_searcher,
        secondary_searcher,
        cross_reference_validator,
        result_synthesizer,
    ],
    instructions=[
        "Work together to provide comprehensive search results using distributed processing.",
        "Primary Searcher: Conduct broad comprehensive search first.",
        "Secondary Searcher: Perform targeted specialized search.",
        "Cross-Reference Validator: Validate consistency across all results.",
        "Result Synthesizer: Combine everything into a ranked, comprehensive response.",
        "Leverage the infinity reranker for high-performance result ranking.",
        "Ensure all results are properly attributed and ranked by relevance.",
    ],
    show_members_responses=True,
    markdown=True,
)


async def async_distributed_search():
    """Demonstrate async distributed search with infinity reranking."""
    print("⚡ Async Distributed Search with Infinity Reranker Demo")
    print("=" * 65)

    query = "How do Agents work with tools and what are the performance considerations?"

    # Add content to both knowledge bases
    await knowledge_primary.add_contents_async(
        urls=["https://docs.agno.com/basics/agents/overview.md"]
    )
    await knowledge_secondary.add_contents_async(
        urls=["https://docs.agno.com/basics/agents/overview.md"]
    )

    # Run async distributed search
    await distributed_search_team.aprint_response(query, stream=True)


def sync_distributed_search():
    """Demonstrate sync distributed search with infinity reranking."""
    print("⚡ Distributed Search with Infinity Reranker Demo")
    print("=" * 55)

    query = "How do Agents work with tools and what are the performance considerations?"

    # Add content to both knowledge bases
    knowledge_primary.add_contents(
        urls=["https://docs.agno.com/basics/agents/overview.md"]
    )
    knowledge_secondary.add_contents(
        urls=["https://docs.agno.com/basics/agents/overview.md"]
    )

    # Run distributed search
    distributed_search_team.print_response(query, stream=True)


if __name__ == "__main__":
    # Choose which demo to run

    try:
        # asyncio.run(async_distributed_search())

        sync_distributed_search()
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\n💡 Make sure Infinity server is running:")
        print("   pip install 'infinity-emb[all]'")
        print("   infinity_emb v2 --model-id BAAI/bge-reranker-base --port 7997")
