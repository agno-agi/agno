"""
This example demonstrates how multiple specialized agents can coordinate to provide
comprehensive RAG (Retrieval-Augmented Generation) responses by dividing search
and analysis tasks across team members.

Team Composition:
- Knowledge Searcher: Searches knowledge base for relevant information
- Content Analyzer: Analyzes and synthesizes retrieved content
- Response Synthesizer: Creates final comprehensive response with sources

Setup:
1. Run: `pip install agno anthropic cohere lancedb tantivy sqlalchemy`
2. Export your ANTHROPIC_API_KEY and CO_API_KEY
3. Run this script to see coordinated RAG in action
"""

from agno.agent import Agent
from agno.knowledge.embedder.cohere import CohereEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.anthropic import Claude
from agno.team.team import Team
from agno.vectordb.lancedb import LanceDb, SearchType

# Shared knowledge base for the team
knowledge = Knowledge(
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs_team",
        search_type=SearchType.hybrid,
        embedder=CohereEmbedder(id="embed-v4.0"),
        reranker=CohereReranker(model="rerank-v3.5"),
    ),
)

# Add documentation content
knowledge.add_contents(urls=["https://docs.agno.com/basics/agents/overview.md"])

# Knowledge Searcher Agent - Specialized in finding relevant information
knowledge_searcher = Agent(
    name="Knowledge Searcher",
    model=Claude(id="claude-3-7-sonnet-latest"),
    role="Search and retrieve relevant information from the knowledge base",
    knowledge=knowledge,
    search_knowledge=True,
    instructions=[
        "You are responsible for searching the knowledge base thoroughly.",
        "Find all relevant information for the user's query.",
        "Provide detailed search results with context and sources.",
        "Focus on comprehensive information retrieval.",
    ],
    markdown=True,
)

# Content Analyzer Agent - Specialized in analyzing retrieved content
content_analyzer = Agent(
    name="Content Analyzer",
    model=Claude(id="claude-3-7-sonnet-latest"),
    role="Analyze and extract key insights from retrieved content",
    instructions=[
        "Analyze the content provided by the Knowledge Searcher.",
        "Extract key concepts, relationships, and important details.",
        "Identify gaps or areas needing additional clarification.",
        "Organize information logically for synthesis.",
    ],
    markdown=True,
)

# Response Synthesizer Agent - Specialized in creating comprehensive responses
response_synthesizer = Agent(
    name="Response Synthesizer",
    model=Claude(id="claude-3-7-sonnet-latest"),
    role="Create comprehensive final response with proper citations",
    instructions=[
        "Synthesize information from team members into a comprehensive response.",
        "Include proper source citations and references.",
        "Ensure accuracy and completeness of the final answer.",
        "Structure the response clearly with appropriate formatting.",
    ],
    markdown=True,
)

# Create coordinated RAG team
coordinated_rag_team = Team(
    name="Coordinated RAG Team",
    model=Claude(id="claude-3-7-sonnet-latest"),
    members=[knowledge_searcher, content_analyzer, response_synthesizer],
    instructions=[
        "Work together to provide comprehensive responses using the knowledge base.",
        "Knowledge Searcher: First search for relevant information thoroughly.",
        "Content Analyzer: Then analyze and organize the retrieved content.",
        "Response Synthesizer: Finally create a well-structured response with sources.",
        "Ensure all responses include proper citations and are factually accurate.",
    ],
    show_members_responses=True,
    markdown=True,
)


def main():
    """Run the coordinated agentic RAG team example."""
    print("🤖 Coordinated Agentic RAG Team Demo")
    print("=" * 50)

    # Example query that benefits from coordinated search and analysis
    query = "What are Agents and how do they work with tools and knowledge?"

    # Run the coordinated team
    coordinated_rag_team.print_response(query, stream=True)


if __name__ == "__main__":
    main()
