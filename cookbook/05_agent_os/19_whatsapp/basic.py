"""
Serve an Agent on WhatsApp
==========================

Mount one Agent on AgentOS's WhatsApp interface. The interface verifies Meta
webhooks, maps each phone number to a persistent session, and sends the Agent's
response back through the WhatsApp Cloud API.

Prerequisites: OPENAI_API_KEY and the four WHATSAPP_* credentials in README.md
Run: .venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/basic.py
Try: GET http://localhost:7777/whatsapp/status, then message the configured number
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp

# ---------------------------------------------------------------------------
# Create the WhatsApp AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="whatsapp-basic-db",
    db_file="tmp/whatsapp_basic.db",
)

assistant = Agent(
    id="whatsapp-assistant",
    name="WhatsApp Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    add_history_to_context=True,
    num_history_runs=3,
    instructions=[
        "You are chatting with the user on WhatsApp.",
        "Keep responses conversational, concise, and easy to read on a phone.",
    ],
)

agent_os = AgentOS(
    id="whatsapp-basic-os",
    description="A minimal AgentOS exposed through the WhatsApp interface.",
    agents=[assistant],
    interfaces=[Whatsapp(agent=assistant)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the WhatsApp Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
