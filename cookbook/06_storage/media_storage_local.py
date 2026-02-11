"""
Example: Using LocalMediaStorage for development and testing.

LocalMediaStorage saves media files to the local filesystem instead of S3.
Useful for local development, testing, and debugging media storage integration
without needing cloud credentials.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media_storage.local import LocalMediaStorage
from agno.models.openai import OpenAIChat
from agno.db.postgres import PostgresDb

# Configure local storage backend
storage = LocalMediaStorage(
    base_path="./tmp/media_storage",
    # Optional: set base_url if serving files via a local HTTP server
    # base_url="http://localhost:8080/media",
)

# Create agent with media storage enabled
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    media_storage=storage,
    db=SqliteDb(db_file="tmp/data.db"),
    # db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai") # Postgres option
)

# Run a query with an image
agent.print_response(
    "What do you see in this image?",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
)

# After running, check ./tmp/media_storage/ for the saved media files
# and .meta.json sidecar files with metadata.
