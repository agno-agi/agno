"""
Multiple WhatsApp Bot Instances
================================

Deploy multiple agents as separate WhatsApp bots on one server.
Each bot needs its own Meta app, phone number, and credentials.

Setup:
  1. Create two WhatsApp Business apps at https://developers.facebook.com
  2. Each app gets its own phone number, access token, and verify token
  3. Set each app's webhook callback URL to its prefix:
       - Basic Bot       ->  https://myapp.com/basic/webhook
       - Research Bot     ->  https://myapp.com/web-research/webhook
  4. Set environment variables (or pass tokens directly):
       BASIC_WHATSAPP_ACCESS_TOKEN, BASIC_WHATSAPP_PHONE_NUMBER_ID, BASIC_WHATSAPP_VERIFY_TOKEN
       RESEARCH_WHATSAPP_ACCESS_TOKEN, RESEARCH_WHATSAPP_PHONE_NUMBER_ID, RESEARCH_WHATSAPP_VERIFY_TOKEN

Note: Unlike Slack (where each app can have its own Event Subscription URL),
Meta only allows ONE webhook callback URL per WhatsApp Business app.
You cannot route two prefixes to the same app — each instance requires
a separate Meta app with its own phone number.
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/persistent_memory.db")

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
)

web_research_agent = Agent(
    name="Web Research Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    db=agent_db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# AgentOS — each WhatsApp interface gets its own credentials
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    agents=[basic_agent, web_research_agent],
    interfaces=[
        Whatsapp(
            agent=basic_agent,
            prefix="/basic",
            access_token=getenv("BASIC_WHATSAPP_ACCESS_TOKEN"),
            phone_number_id=getenv("BASIC_WHATSAPP_PHONE_NUMBER_ID"),
            verify_token=getenv("BASIC_WHATSAPP_VERIFY_TOKEN"),
        ),
        Whatsapp(
            agent=web_research_agent,
            prefix="/web-research",
            access_token=getenv("RESEARCH_WHATSAPP_ACCESS_TOKEN"),
            phone_number_id=getenv("RESEARCH_WHATSAPP_PHONE_NUMBER_ID"),
            verify_token=getenv("RESEARCH_WHATSAPP_VERIFY_TOKEN"),
        ),
    ],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="multiple_instances:app", reload=True)
