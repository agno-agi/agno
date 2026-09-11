"""AgentOS with JWT-authenticated, per-user durable files.

Set OPENAI_API_KEY and JWT_VERIFICATION_KEY (a strong HS256 signing secret).
Use short-lived tokens with aud=isolated-files-os and sub identifying the user.
Ask: Save my project preferences to notes/preferences.md.
"""

from os import environ

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

db = SqliteDb(id="isolated-files-db", db_file="tmp/isolated_files.db")

agent = Agent(
    id="personal-assistant",
    name="Personal Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    filesystem=True,
    instructions="Keep the user's durable notes in your filesystem. Save notes only when asked.",
    markdown=True,
)

# Managed files use users/{verified_user_id}/agents/personal-assistant.
agent_os = AgentOS(
    id="isolated-files-os",
    db=db,
    agents=[agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[environ["JWT_VERIFICATION_KEY"]],
        algorithm="HS256",
        verify_audience=True,
        user_isolation=True,
    ),
    cors_allowed_origins=["http://localhost:3000"],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7777)
