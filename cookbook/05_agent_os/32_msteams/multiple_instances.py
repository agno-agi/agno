"""
Mount Multiple Microsoft Teams Bots
====================================

Use two app registrations with separate credentials and callback prefixes.
Prerequisites: OPENAI_API_KEY and the six bot-specific variables in README.md
Run: python cookbook/05_agent_os/32_msteams/multiple_instances.py
Try: Message both bots and verify that their histories remain separate.
"""

from os import environ

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.msteams import MSTeams
from agno.tools.websearch import WebSearchTools

# The same database is safe here because each bot has a distinct entity id.
db = SqliteDb(id="msteams-multiple-db", db_file="tmp/msteams_multiple.db")
basic_bot = Agent(
    id="msteams-basic-bot",
    name="Teams Basic Bot",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    add_history_to_context=True,
    instructions="Answer clearly and concisely.",
)
research_bot = Agent(
    id="msteams-research-bot",
    name="Teams Research Bot",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
    instructions="Research current information and cite useful sources.",
)
agent_os = AgentOS(
    id="msteams-multiple-os",
    agents=[basic_bot, research_bot],
    interfaces=[
        MSTeams(
            agent=basic_bot,
            prefix="/basic",
            app_id=environ["BASIC_MICROSOFT_APP_ID"],
            app_password=environ["BASIC_MICROSOFT_APP_PASSWORD"],
            tenant_id=environ["BASIC_MICROSOFT_APP_TENANT_ID"],
        ),
        MSTeams(
            agent=research_bot,
            prefix="/research",
            app_id=environ["RESEARCH_MICROSOFT_APP_ID"],
            app_password=environ["RESEARCH_MICROSOFT_APP_PASSWORD"],
            tenant_id=environ["RESEARCH_MICROSOFT_APP_TENANT_ID"],
        ),
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app)
