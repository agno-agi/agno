from agno.agent import Agent
from agno.db.surrealdb import SurrealDb

from agno.knowledge.knowledge import Knowledge
from agno.vectordb.surrealdb import SurrealDb as SurrealDbVector
from surrealdb import Surreal

from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
pg_vector_db = PgVector(table_name="docs", db_url=db_url)

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "agno"
SURREALDB_DATABASE = "surrealdb_for_agent_with_knowledge"

# Create a client
client = Surreal(url=SURREALDB_URL)
client.signin({"username": SURREALDB_USER, "password": SURREALDB_PASSWORD})
client.use(namespace=SURREALDB_NAMESPACE, database=SURREALDB_DATABASE)

surreal_vector_db = SurrealDbVector(
    client=client,
    collection="recipes",  # Collection name for storing documents
    efc=150,  # HNSW construction time/accuracy trade-off
    m=12,  # HNSW max number of connections per element
    search_ef=40,  # HNSW search time/accuracy trade-off
    embedder=OpenAIEmbedder(),
)



creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE)

knowledge = Knowledge(
    contents_db=db,
    vector_db=pg_vector_db,
)

knowledge.add_content(
    url="https://docs.agno.com/llms-full.txt"
)

agent = Agent(knowledge=knowledge)

if __name__ == "__main__":
    agent.print_response("What can you tell me about Agno docs?", stream=True)