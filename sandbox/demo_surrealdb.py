import asyncio
from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.surrealdb import SurrealVectorDb
from agno.embedder.openai import OpenAIEmbedder

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "test"
SURREALDB_DATABASE = "test"

surrealdb = SurrealVectorDb(
        url=SURREALDB_URL,
        username=SURREALDB_USER,
        password=SURREALDB_PASSWORD,
        namespace=SURREALDB_NAMESPACE,
        database=SURREALDB_DATABASE,
        collection="recipes",  # Collection name for storing documents
        efc=150,  # HNSW construction time/accuracy trade-off
        m=12,    # HNSW max number of connections per element
        search_ef=40  # HNSW search time/accuracy trade-off
    )

def sync_demo():
    """Demonstrate synchronous usage of SurrealVectorDb"""
    knowledge_base = PDFUrlKnowledgeBase(
        urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
        vector_db=surrealdb,
        embedder=OpenAIEmbedder(),
    )

    # Load data synchronously
    knowledge_base.load(recreate=True)

    # Create agent and query synchronously
    agent = Agent(knowledge=knowledge_base, show_tool_calls=True, debug_mode=True)
    agent.print_response("What are the 3 categories of Thai SELECT is given to restaurants overseas?", markdown=True)

async def async_demo():
    """Demonstrate asynchronous usage of SurrealVectorDb"""
    knowledge_base = PDFUrlKnowledgeBase(
        urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
        vector_db=surrealdb,
        embedder=OpenAIEmbedder(),
    )

    # Load data synchronously
    await knowledge_base.aload(recreate=True)

    # Create agent and query synchronously
    agent = Agent(knowledge=knowledge_base, show_tool_calls=True, debug_mode=True)
    await agent.aprint_response("What are the 3 categories of Thai SELECT is given to restaurants overseas?", markdown=True)

if __name__ == "__main__":
    # Run synchronous demo
    # print("Running synchronous demo...")
    # sync_demo()

    # Run asynchronous demo
    print("\nRunning asynchronous demo...")
    asyncio.run(async_demo())