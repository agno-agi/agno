"""
Remember Slack Users Across Threads
===================================

Resolve a Slack member to an email-backed user ID when available, then use a
MemoryManager to retain stable preferences across otherwise separate threads.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/user_memory.py
Try in Slack: Share a preference in one thread, then ask about it in a new thread
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history, users:read, users:read.email
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory import MemoryManager
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack

# ---------------------------------------------------------------------------
# Create Memory-enabled Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-memory-db",
    db_file="tmp/slack_memory.db",
)

memory_manager = MemoryManager(
    id="slack-user-memory-manager",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    memory_capture_instructions=(
        "Capture the user's name, role, communication preferences, current "
        "projects, and durable likes or dislikes."
    ),
)

personal_assistant = Agent(
    id="slack-personal-assistant",
    name="Slack Personal Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    memory_manager=memory_manager,
    update_memory_on_run=True,
    instructions=[
        "Use saved user memories when they are relevant.",
        "Do not invent personal details that are not in the conversation or memory.",
        "Keep responses concise for Slack.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(
    id="slack-memory-os",
    description="AgentOS with email-resolved Slack user memory.",
    agents=[personal_assistant],
    interfaces=[
        Slack(
            agent=personal_assistant,
            resolve_user_identity=True,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Memory-enabled Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
