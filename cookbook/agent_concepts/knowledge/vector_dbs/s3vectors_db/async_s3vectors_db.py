"""Example of using S3Vectors with async operations for knowledge base queries."""

import asyncio

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.s3vectors import S3VectorsDb

vector_db = S3VectorsDb(
    bucket_name="recipe-vectors",
    index_name="recipe-index",
    dimension=1536,
    region_name="us-east-1",
)

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

agent = Agent(knowledge=knowledge_base, show_tool_calls=True)


async def main():
    """Run async knowledge base operations."""
    # Load knowledge base on first run
    await knowledge_base.aload(recreate=True)
    
    # Query the knowledge base
    await agent.aprint_response("How to make Tom Kha Gai", markdown=True)


if __name__ == "__main__":
    asyncio.run(main())
