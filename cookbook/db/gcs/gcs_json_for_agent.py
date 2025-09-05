import uuid

import google.auth
from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.gcs_json import GcsJsonDb
from agno.tools.duckduckgo import DuckDuckGoTools

DEBUG_MODE = False
# Obtain the default credentials and project id from your gcloud CLI session.
credentials, project_id = google.auth.default()

# Generate a unique bucket name using a base name and a UUID4 suffix.
base_bucket_name = "example-gcs-bucket"
unique_bucket_name = f"{base_bucket_name}-{uuid.uuid4().hex[:12]}"
print(f"Using bucket: {unique_bucket_name}")

# Initialize GCSJsonDb with explicit credentials, unique bucket name, and project.
db = GcsJsonDb(
    bucket_name=unique_bucket_name,
    prefix="agent/",
    project=project_id,
    credentials=credentials,
)

# Initialize the Agno agent1 with the new storage backend and a DuckDuckGo search tool.
agent1 = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    debug_mode=DEBUG_MODE,
)

# Execute sample queries.
agent1.print_response("How many people live in Canada?")
agent1.print_response("What is their national anthem called?")

# create a new agent and make sure it pursues the conversation
agent2 = Agent(
    db=db,
    session_id=agent1.session_id,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    debug_mode=DEBUG_MODE,
)

agent2.print_response("What's the name of the country we discussed?")
agent2.print_response("What is that country's national sport?")

# After running the agent1, print the content of the bucket: blob names and JSON content.
if DEBUG_MODE:
    print(f"\nBucket {db.bucket_name} contents:")
    sessions = db.get_sessions(session_type=SessionType.AGENT)
    for session in sessions:
        print(f"Session {session.session_id}:\n\t{session.memory}")  # type: ignore
        print("-" * 40)
