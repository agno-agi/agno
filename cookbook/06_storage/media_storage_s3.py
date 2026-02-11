"""
Example: Using S3MediaStorage to offload media to external object storage.

When media_storage is configured, media content (images, audio, video, files)
is uploaded to S3 before being stored in the database. Only lightweight
MediaReference objects (with pre-signed URLs) are stored in the DB, dramatically
reducing database size.

Requirements:
    pip install 'agno[media-storage-s3]'

Environment:
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION (or configure via boto3)
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media_storage.s3 import S3MediaStorage
from agno.models.openai import OpenAIChat

# Configure S3 storage backend
storage = S3MediaStorage(
    bucket="my-agno-media",
    region="us-east-1",
    prefix="agno/media/",
    presigned_url_expiry=3600,  # 1 hour
)

# Create agent with media storage enabled
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # Session DBs to store only lightweight media references (with pre-signed URLs), while the
    db=SqliteDb(db_file="tmp/data.db"),
    # db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai") # Postgres option
    media_storage=storage,
    # store_media=True is the default; when combined with media_storage,
    # media is uploaded to S3 and only references are stored in the DB.
)

# Image is sent to the model as base64 (for inference), but uploaded to S3
# and only a reference (with pre-signed URL) is stored in the database.
agent.print_response(
    "Describe this image in detail.",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
)
