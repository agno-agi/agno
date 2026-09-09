"""
Mount Multiple WhatsApp Bot Instances
=====================================

Mount two independently configured WhatsApp interfaces on one AgentOS. Each
interface has its own prefix, access token, phone-number ID, and verification
token, so its Meta webhook points at a distinct callback URL.

Prerequisites: OPENAI_API_KEY and the six bot-specific variables in README.md
Run: .venvs/demo/bin/python cookbook/05_agent_os/19_whatsapp/multiple_instances.py
Try: GET /basic/status and /web-research/status, then verify both webhook URLs

Security note: signed POST requests currently share one global
WHATSAPP_APP_SECRET. See README.md before deploying separate Meta apps.
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.tools.websearch import WebSearchTools


def required_env(name: str) -> str:
    value = getenv(name)
    if not value:
        raise ValueError(f"{name} is required for this example")
    return value


# ---------------------------------------------------------------------------
# Create the Multi-Bot WhatsApp AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="whatsapp-multiple-db",
    db_file="tmp/whatsapp_multiple.db",
)

basic_bot = Agent(
    id="whatsapp-basic-bot",
    name="WhatsApp Basic Bot",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    add_history_to_context=True,
    num_history_runs=3,
    instructions="Answer clearly and concisely.",
)

research_bot = Agent(
    id="whatsapp-research-bot",
    name="WhatsApp Research Bot",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
    num_history_runs=3,
    instructions="Research current information and cite useful sources.",
)

agent_os = AgentOS(
    id="whatsapp-multiple-os",
    description="Two WhatsApp bots mounted at separate AgentOS prefixes.",
    agents=[basic_bot, research_bot],
    interfaces=[
        Whatsapp(
            agent=basic_bot,
            prefix="/basic",
            access_token=required_env("BASIC_WHATSAPP_ACCESS_TOKEN"),
            phone_number_id=required_env("BASIC_WHATSAPP_PHONE_NUMBER_ID"),
            verify_token=required_env("BASIC_WHATSAPP_VERIFY_TOKEN"),
        ),
        Whatsapp(
            agent=research_bot,
            prefix="/web-research",
            access_token=required_env("RESEARCH_WHATSAPP_ACCESS_TOKEN"),
            phone_number_id=required_env("RESEARCH_WHATSAPP_PHONE_NUMBER_ID"),
            verify_token=required_env("RESEARCH_WHATSAPP_VERIFY_TOKEN"),
        ),
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the Multi-Bot WhatsApp Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
