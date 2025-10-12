"""
Valkey Search Vector Database Example

This example demonstrates how to use Valkey Search as a vector database with Agno.
Valkey Search is a search engine that supports vector similarity search.

Prerequisites:
1. Start Valkey with Docker Compose:
   cd cookbook/knowledge/vector_db/valkey_db/
   docker-compose up -d

2. Set your OpenAI API key:
   export OPENAI_API_KEY="your-api-key-here"
"""
from agno.vectordb.valkey import ValkeySearch
from agno.knowledge.knowledge import Knowledge
from agno.agent import Agent
import asyncio

if __name__ == "__main__":
    # Valkey Search example loading PDF from URL
    knowledge = Knowledge(
        name="Valkey Knowledge Base",
        description="Agno Knowledge Implementation with Valkey Search",
        vector_db=ValkeySearch(
            collection="vectors",
            host="localhost",
            port=6379,
        ),
    )

    # Add PDF content from URL
    asyncio.run(
        knowledge.add_content_async(
            name="Recipes",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            metadata={"doc_type": "recipe_book"},
        )
    )

    # Create and use the agent
    agent = Agent(knowledge=knowledge)
    agent.print_response("List down the ingredients to make Massaman Gai", markdown=True)