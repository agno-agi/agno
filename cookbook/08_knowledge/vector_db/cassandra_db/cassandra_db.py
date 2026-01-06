from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.cassandra import Cassandra

try:
    from cassandra.cluster import Cluster  # type: ignore
except (ImportError, ModuleNotFoundError):
    raise ImportError(
        "Could not import cassandra-driver python package.Please install it with pip install cassandra-driver."
    )

cluster = Cluster()

session = cluster.connect()
session.execute(
    """
    CREATE KEYSPACE IF NOT EXISTS testkeyspace
    WITH REPLICATION = { 'class' : 'SimpleStrategy', 'replication_factor' : 1 }
    """
)
vector_db = Cassandra(
    table_name="recipes",
    keyspace="testkeyspace",
    session=session,
    embedder=OpenAIEmbedder(
        dimensions=1024,
    ),
)

knowledge = Knowledge(
    name="My Cassandra Knowledge Base",
    vector_db=vector_db,
)


knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

agent = Agent(
    knowledge=knowledge,
)

agent.print_response(
    "What are the health benefits of Khao Niew Dam Piek Maphrao Awn?",
    markdown=True,
    show_full_reasoning=True,
)

vector_db.delete_by_name("Recipes")
# or
vector_db.delete_by_metadata({"doc_type": "recipe_book"})
