"""
Async example of using Gemini File Search as a vector database.

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

# Initialize Gemini File Search
vector_db = GeminiFileSearch(
    file_search_store_name="agno-docs-store",
    model_name="gemini-2.5-flash-lite",
    api_key=api_key,
)

# Create knowledge base
knowledge = Knowledge(
    name="Agno Documentation",
    description="Knowledge base with Agno documentation using Gemini File Search",
    vector_db=vector_db,
)

# Create and use the agent
agent = Agent(knowledge=knowledge, search_knowledge=True)


async def main():
    """Main async function."""
    # Add content to the knowledge base
    # Comment out after first run to avoid re-uploading
    await knowledge.add_content_async(
        name="AgnoIntroduction",
        url="https://docs.agno.com/concepts/agents/introduction.md",
        metadata={"doc_type": "documentation", "topic": "agents"},
    )

    # Query the knowledge base using async
    await agent.aprint_response("What is the purpose of an Agno Agent?", markdown=True)

    # Additional query
    await agent.aprint_response(
        "How do I create an agent with knowledge?", markdown=True
    )


if __name__ == "__main__":
    asyncio.run(main())
