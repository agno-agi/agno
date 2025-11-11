"""Run `pip install lancedb` to install dependencies."""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.knowledge.embedder.ollama import OllamaEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.ollama import Ollama
from agno.vectordb.lancedb import LanceDb

# Define the database URL where the vector database will be stored
db_url = "/tmp/lancedb"

# Configure the language model
model = Ollama(id="llama3.1:8b")

# Create Ollama embedder
embedder = OllamaEmbedder(id="nomic-embed-text", dimensions=768)

# Create the vector database
vector_db = LanceDb(
    table_name="recipes",  # Table name in the vector database
    uri=db_url,  # Location to initiate/create the vector database
    embedder=embedder,  # Without using this, it will use OpenAIChat embeddings by default
)

knowledge = Knowledge(
    vector_db=vector_db,
)

knowledge.add_content(
    name="Recipes", url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
)


# Set up SQL storage for the agent's data
db = SqliteDb(db_file="data.db")

# Initialize the Agent with various configurations including the knowledge base and storage
agent = Agent(
    session_id="session_id",  # use any unique identifier to identify the run
    user_id="user",  # user identifier to identify the user
    model=model,
    knowledge=knowledge,
    db=db,
)

# Use the agent to generate and print a response to a query, formatted in Markdown
agent.print_response(
    "What is the first step of making Gluai Buat Chi from the knowledge base?",
    markdown=True,
)
