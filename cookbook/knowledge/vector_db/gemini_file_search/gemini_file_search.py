"""
Basic example of using Gemini File Search as a vector database.

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
    file_search_store_name="thai-recipes-store",
    model_name="gemini-2.5-flash-lite",
    api_key=api_key,
)

# Create Knowledge Instance with Gemini File Search
knowledge = Knowledge(
    name="Thai Recipe Knowledge Base",
    description="Agno 2.0 Knowledge Implementation with Gemini File Search",
    vector_db=vector_db,
)

# Add content to the knowledge base
# Note: This uploads documents to Gemini File Search Store
asyncio.run(
    knowledge.add_content_async(
        name="Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"doc_type": "recipe_book", "cuisine": "Thai"},
    )
)

# Create and use the agent
agent = Agent(knowledge=knowledge, search_knowledge=True)

# Query the knowledge base
agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)

# Delete operations examples
# Delete by name
vector_db.delete_by_name("Recipes")

# Note: delete_by_metadata is not supported by Gemini File Search
# You can only delete documents by name or ID
