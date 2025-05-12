import asyncio
from typing import Optional

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.qdrant import Qdrant
from qdrant_client import AsyncQdrantClient

# ---------------------------------------------------------
# This section loads the knowledge base. Skip if your knowledge base was populated elsewhere.
# Define the embedder
embedder = OpenAIEmbedder(id="text-embedding-3-small")
# Initialize vector database connection
vector_db = Qdrant(collection="thai-recipes", path="tmp/qdrant", embedder=embedder)
# Load the knowledge base
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

# Load the knowledge base
# knowledge_base.load(recreate=True)  # Comment out after first run
# Knowledge base is now loaded
# ---------------------------------------------------------


# Define the custom async retriever
# This is the function that the agent will use to retrieve documents
async def retriever(
    query: str, agent: Optional[Agent] = None, num_documents: int = 5, **kwargs
) -> Optional[list[dict]]:
    """
    Custom async retriever function to search the vector database for relevant documents.

    Args:
        query (str): The search query string
        agent (Agent): The agent instance making the query
        num_documents (int): Number of documents to retrieve (default: 5)
        **kwargs: Additional keyword arguments

    Returns:
        Optional[list[dict]]: List of retrieved documents or None if search fails
    """
    try:
        qdrant_client = AsyncQdrantClient(path="tmp/qdrant")
        query_embedding = embedder.get_embedding(query)
        results = await qdrant_client.query_points(
            collection_name="thai-recipes",
            query=query_embedding,
            limit=num_documents,
        )
        results_dict = results.model_dump()
        if "points" in results_dict:
            return results_dict["points"]
        else:
            return None
    except Exception as e:
        print(f"Error during vector database search: {str(e)}")
        return None


async def amain():
    """Async main function to demonstrate agent usage."""
    # Initialize agent with custom retriever
    # Remember to set search_knowledge=True to use agentic_rag or add_reference=True for traditional RAG
    # search_knowledge=True is default when you add a knowledge base but is needed here
    agent = Agent(
        retriever=retriever,
        knowledge=knowledge_base,
        search_knowledge=True,
        instructions="Search the knowledge base for information",
        show_tool_calls=True,
    )

    # Load the knowledge base (uncomment for first run)
    await knowledge_base.aload(recreate=True)

    # Example query
    query = "List down the ingredients to make Massaman Gai"
    await agent.aprint_response(query, markdown=True)


def main():
    """Synchronous wrapper for main function"""
    asyncio.run(amain())


if __name__ == "__main__":
    main()
