from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.surrealdb import SurrealVectorDb

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "test"
SURREALDB_DATABASE = "test"

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=SurrealVectorDb(
        url=SURREALDB_URL,
        username=SURREALDB_USER,
        password=SURREALDB_PASSWORD,
        namespace=SURREALDB_NAMESPACE,
        database=SURREALDB_DATABASE,
        collection="recipes",  # Collection name for storing documents
        dimension=1536,  # OpenAI's text-embedding-ada-002 dimension
        efc=150,  # HNSW construction time/accuracy trade-off
        m=12,    # HNSW max number of connections per element
        search_ef=40  # HNSW search time/accuracy trade-off
    ),
)

# Uncomment to load data on first run
knowledge_base.load(recreate=True)

agent = Agent(knowledge=knowledge_base, show_tool_calls=True)
agent.print_response("How to make Thai curry?", markdown=True)