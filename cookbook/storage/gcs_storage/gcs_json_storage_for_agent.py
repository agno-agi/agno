import uuid

import google.auth
from agno.agent import Agent
from agno.storage.gcs_json import GCSJsonStorage
from agno.tools.duckduckgo import DuckDuckGoTools

DEBUG_MODE = False
# Obtain the default credentials and project id from your gcloud CLI session.
credentials, project_id = google.auth.default()

# Generate a unique bucket name using a base name and a UUID4 suffix.
base_bucket_name = "example-gcs-bucket"
unique_bucket_name = f"{base_bucket_name}-{uuid.uuid4().hex[:12]}"  # 12 hex digits for brevity
print(f"Using bucket: {unique_bucket_name}")

# Initialize GCSJsonStorage with explicit credentials, unique bucket name, and project.
storage = GCSJsonStorage(
    credentials=credentials,
    bucket_name=unique_bucket_name,
    project=project_id,
)

# Create the bucket (if it doesn't exist, it will be created).
storage.create()


# Initialize the Agno agent1 with the new storage backend and a DuckDuckGo search tool.
agent1 = Agent(
    storage=storage,
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
    debug_mode=DEBUG_MODE,
)

# Execute sample queries.
agent1.print_response("How many people live in Canada?")
agent1.print_response("What is their national anthem called?")

# create a new agent and make sure it pursues the conversation
agent2 = Agent(
    storage=storage,
    session_id=agent1.session_id,
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
    debug_mode=DEBUG_MODE,
)

agent2.print_response("What's the name of the country we discussed?")
agent2.print_response("What is that country's national sport?")

# After running the agent1, print the content of the bucket: blob names and JSON content.
if DEBUG_MODE:
    print("\nBucket contents:")
    for blob in storage.client.list_blobs(storage.bucket, prefix=""):
        print(f"Blob name: {blob.name}")
        try:
            content = blob.download_as_string().decode("utf-8")
            print("Content:")
            print(content)
        except Exception as e:
            print(f"Error reading blob {blob.name}: {e}")
        print("-" * 40)
