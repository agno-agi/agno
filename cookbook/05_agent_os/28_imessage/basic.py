"""
Serve an Agent through iMessage
==============================

Receive direct iMessage text messages through a BlueBubbles server on a Mac.
See README.md for bridge setup and the required environment variables.

Run: .venvs/demo/bin/python cookbook/05_agent_os/28_imessage/basic.py
"""

from os import environ

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.imessage import IMessage

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

imessage_assistant = Agent(
    id="imessage-assistant",
    name="iMessage Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(id="imessage-db", db_file="tmp/imessage.db"),
    instructions=[
        "You are a helpful assistant on iMessage.",
        "Keep replies concise and use plain text.",
    ],
    add_history_to_context=True,
    num_history_runs=5,
    markdown=False,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="imessage-os",
    agents=[imessage_assistant],
    interfaces=[
        IMessage(
            agent=imessage_assistant,
            allowed_senders=[
                sender.strip()
                for sender in environ["IMESSAGE_ALLOWED_SENDERS"].split(",")
                if sender.strip()
            ],
        )
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", workers=1, access_log=False)
