"""
This example demonstrates how multiple specialized agents coordinate to provide
comprehensive RAG responses using distributed knowledge bases and specialized
retrieval strategies with LanceDB.

Team Composition:
- Primary Retriever: Handles primary document retrieval from main knowledge base
- Context Expander: Expands context by finding related information
- Answer Synthesizer: Synthesizes retrieved information into comprehensive answers
- Quality Validator: Validates answer quality and suggests improvements

Setup:
1. Run: `pip install openai lancedb tantivy pypdf sqlalchemy agno`
2. Run this script to see distributed RAG in action
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.vectordb.lancedb import LanceDb, SearchType

# Primary knowledge base for main retrieval
primary_knowledge = Knowledge(
    vector_db=LanceDb(
        table_name="recipes_primary",
        uri="tmp/lancedb",
        search_type=SearchType.vector,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Secondary knowledge base for context expansion
context_knowledge = Knowledge(
    vector_db=LanceDb(
        table_name="recipes_context",
        uri="tmp/lancedb",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Primary Retriever Agent - Specialized in main document retrieval
primary_retriever = Agent(
    name="Primary Retriever",
    model=OpenAIChat(id="o3-mini"),
    role="Retrieve primary documents and core information from knowledge base",
    knowledge=primary_knowledge,
    search_knowledge=True,
    instructions=[
        "Search the knowledge base for directly relevant information to the user's query.",
        "Focus on retrieving the most relevant and specific documents first.",
        "Provide detailed information with proper context.",
        "Ensure accuracy and completeness of retrieved information.",
    ],
    markdown=True,
)

# Context Expander Agent - Specialized in expanding context
context_expander = Agent(
    name="Context Expander",
    model=OpenAIChat(id="o3-mini"),
    role="Expand context by finding related and supplementary information",
    knowledge=context_knowledge,
    search_knowledge=True,
    instructions=[
        "Find related information that complements the primary retrieval.",
        "Look for background context, related topics, and supplementary details.",
        "Search for information that helps understand the broader context.",
        "Identify connections between different pieces of information.",
    ],
    markdown=True,
)

# Answer Synthesizer Agent - Specialized in synthesis
answer_synthesizer = Agent(
    name="Answer Synthesizer",
    model=OpenAIChat(id="o3-mini"),
    role="Synthesize retrieved information into comprehensive answers",
    instructions=[
        "Combine information from the Primary Retriever and Context Expander.",
        "Create a comprehensive, well-structured response.",
        "Ensure logical flow and coherence in the final answer.",
        "Include relevant details while maintaining clarity.",
        "Organize information in a user-friendly format.",
    ],
    markdown=True,
)

# Quality Validator Agent - Specialized in validation
quality_validator = Agent(
    name="Quality Validator",
    model=OpenAIChat(id="o3-mini"),
    role="Validate answer quality and suggest improvements",
    instructions=[
        "Review the synthesized answer for accuracy and completeness.",
        "Check if the answer fully addresses the user's query.",
        "Identify any gaps or areas that need clarification.",
        "Suggest improvements or additional information if needed.",
        "Ensure the response meets high quality standards.",
    ],
    markdown=True,
)

# Create distributed RAG team
distributed_rag_team = Team(
    name="Distributed RAG Team",
    model=OpenAIChat(id="o3-mini"),
    members=[
        primary_retriever,
        context_expander,
        answer_synthesizer,
        quality_validator,
    ],
    instructions=[
        "Work together to provide comprehensive, high-quality RAG responses.",
        "Primary Retriever: First retrieve core relevant information.",
        "Context Expander: Then expand with related context and background.",
        "Answer Synthesizer: Synthesize all information into a comprehensive answer.",
        "Quality Validator: Finally validate and suggest any improvements.",
        "Ensure all responses are accurate, complete, and well-structured.",
    ],
    show_members_responses=True,
    markdown=True,
)


async def async_distributed_rag_demo():
    """Demonstrate async distributed RAG processing."""
    print("📚 Async Distributed RAG with LanceDB Demo")
    print("=" * 50)

    query = "How do I make chicken and galangal in coconut milk soup? Include cooking tips and variations."

    # Add content to knowledge bases
    await primary_knowledge.add_contents_async(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )
    await context_knowledge.add_contents_async(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )

    # # Run async distributed RAG
    # await distributed_rag_team.aprint_response(
    #     query, stream=True
    # )
    await distributed_rag_team.aprint_response(input=query)


def sync_distributed_rag_demo():
    """Demonstrate sync distributed RAG processing."""
    print("📚 Distributed RAG with LanceDB Demo")
    print("=" * 40)

    query = "How do I make chicken and galangal in coconut milk soup? Include cooking tips and variations."

    # Add content to knowledge bases
    primary_knowledge.add_contents(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )
    context_knowledge.add_contents(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )

    # Run distributed RAG
    distributed_rag_team.print_response(input=query)


def multi_course_meal_demo():
    """Demonstrate distributed RAG for complex multi-part queries."""
    print("🍽️ Multi-Course Meal Planning with Distributed RAG")
    print("=" * 55)

    query = """Hi, I want to make a 3 course Thai meal. Can you recommend some recipes?
    I'd like to start with a soup, then a thai curry for the main course and finish with a dessert.
    Please include cooking techniques and any special tips."""

    # Add content to knowledge bases
    primary_knowledge.add_contents(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )
    context_knowledge.add_contents(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )

    distributed_rag_team.print_response(input=query)


if __name__ == "__main__":
    # Choose which demo to run
    asyncio.run(async_distributed_rag_demo())

    # multi_course_meal_demo()

    # sync_distributed_rag_demo()
