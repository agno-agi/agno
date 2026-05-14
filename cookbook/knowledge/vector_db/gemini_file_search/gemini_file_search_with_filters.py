"""
Example of using Gemini File Search with metadata filters.

Requirements:
- pip install google-genai
- Set GOOGLE_API_KEY environment variable
"""

import asyncio
from os import getenv

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.gemini.gemini_file_search import GeminiFileSearch

# Get API key from environment
api_key = getenv("GOOGLE_API_KEY")

# Create Gemini File Search vector database
vector_db = GeminiFileSearch(
    file_search_store_name="multi-cuisine-recipes",
    model_name="gemini-2.5-flash-lite",
    api_key=api_key,
)

# Create Knowledge Instance
knowledge = Knowledge(
    name="Multi-Cuisine Recipe Knowledge Base",
    description="Knowledge base with recipes from different cuisines",
    vector_db=vector_db,
)


async def add_recipes():
    """Add multiple recipe documents with different metadata."""
    # Add Thai recipes
    await knowledge.add_content_async(
        name="ThaiRecipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"cuisine": "Thai", "difficulty": "medium"},
    )

    # You can add more recipes from other sources with different metadata
    # await knowledge.add_content_async(
    #     name="ItalianRecipes",
    #     content="Italian recipe content here...",
    #     metadata={"cuisine": "Italian", "difficulty": "easy"},
    # )


async def main():
    """Main function."""
    # Add content (comment out after first run)
    await add_recipes()

    # Create agent
    agent = Agent(knowledge=knowledge, search_knowledge=True)

    # Query with specific filters
    # Note: Gemini File Search supports metadata filtering in search
    print("\n=== Searching for Thai recipes ===\n")
    await agent.aprint_response(
        "What are some popular Thai dishes?",
        markdown=True,
    )

    # You can also search the vector database directly with filters
    print("\n=== Direct vector DB search with filters ===\n")
    results = vector_db.search(
        query="coconut curry recipes",
        limit=3,
        filters={"cuisine": "Thai"},  # Filter by cuisine
    )

    for i, result in enumerate(results, 1):
        print(f"\nResult {i}:")
        print(f"Content: {result.content[:200]}...")
        if result.meta_data:
            print(f"Metadata: {result.meta_data}")


if __name__ == "__main__":
    asyncio.run(main())
