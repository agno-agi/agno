from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp.whatsapp import Whatsapp
from agno.tools.googlesearch import GoogleSearchTools

db = SqliteDb(db_file="tmp/memory.db")

personal_agent = Agent(
    name="Basic Agent",
    model=Gemini(id="gemini-2.0-flash"),
    tools=[GoogleSearchTools()],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
    db=db,
    enable_agentic_memory=True,
    instructions=dedent("""
        You are a personal AI friend of the user, your purpose is to chat with the user about things and make them feel good.
        First introduce yourself and ask for their name then, ask about themeselves, their hobbies, what they like to do and what they like to talk about.
        Use Google Search tool to find latest infromation about things in the conversations
                        """),
    debug_mode=True,
)


# Setup our AgentOS app
agent_os = AgentOS(
    description="AgentOS setup with a Whatsapp interface",
    agents=[personal_agent],
    interfaces=[Whatsapp(agent=personal_agent)],
)

app = agent_os.get_app()


if __name__ == "__main__":
    """Run our AgentOS.

    You can see the configuration and available interfaces on:
    http://localhost:7777/config

    """
    agent_os.serve(app="agent_with_user_memory:app", reload=True)
