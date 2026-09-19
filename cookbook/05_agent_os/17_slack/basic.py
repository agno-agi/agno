"""
Serve an Agent in Slack
=======================

Mount one persistent Agent on the Slack interface. Direct messages are always
answered; reply_to_mentions_only only filters non-mention messages in channels.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/basic.py
Try in Slack: In one thread, say "My project is Cedar", then ask what the project is
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack

# ---------------------------------------------------------------------------
# Create Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-basic-db",
    db_file="tmp/slack_basic.db",
)

assistant = Agent(
    id="slack-assistant",
    name="Slack Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are a helpful assistant in Slack.",
        "Keep answers concise and easy to scan.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

agent_os = AgentOS(
    id="slack-basic-os",
    description="AgentOS serving one persistent Slack assistant.",
    agents=[assistant],
    interfaces=[
        Slack(
            agent=assistant,
            reply_to_mentions_only=True,
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
