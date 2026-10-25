"""
AgentOS File System With User Isolation
=======================================

Each verified user gets their own files. ``user_isolation=True`` on AgentOS
keeps every agent filesystem per user: a run reads and writes only its user's
files, users see only their own files in the File System page, and admins see
everyone's.

Tokens are verified with the RS256 public key below, so tokens issued by the
Agno control plane work as-is; their ``sub`` identifies the user.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/with_user_isolation.py
Try: Connect Agno OS to http://localhost:7777, ask "Save my project preferences
to notes/preferences.md", then open File System as another user
"""

from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.fs import FileSystem
from agno.fs.local import LocalFileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization

db = PostgresDb(
    id="agentos-knowledge-postgres",
    db_url=getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
)

jwt_verification_key = """your public key here"""

# Files on local disk. With user isolation on, each user's files live in their
# own folder under tmp/agent-files.
files = FileSystem(
    backend=LocalFileSystem(root="./tmp/agent-files"),
    namespace="research",
)

agent = Agent(
    id="personal-assistant",
    name="Personal Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    filesystem=files,
    instructions="Keep the user's durable notes in your filesystem. Save notes only when asked.",
    markdown=True,
)

agent_os = AgentOS(
    id="isolated-files-os",
    db=db,
    agents=[agent],
    authorization=Authorization(
        verification_keys=[jwt_verification_key],
        algorithm="RS256",
    ),
    user_isolation=True,
    cors_allowed_origins=["http://localhost:3000"],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7777)
