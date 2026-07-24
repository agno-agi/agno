"""
Personal Agent: a generalist with tools of its own and remote specialists as contacts.

The personal agent handles everyday questions with its own tools and messages
remote contacts for specialized work: the news agent on the news agency AgentOS
for the latest news, and the coding agent (with GitHub access) for programming
work like debugging or opening issues and pull requests.

Start the news agency server first: python cookbook/05_agent_os/contacts/server.py
Then run: python cookbook/05_agent_os/contacts/04_personal_agent.py
"""

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.contacts import Contact
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.calculator import CalculatorTools
from agno.tools.websearch import WebSearchTools

db = SqliteDb(id="personal-agent-db", db_file="tmp/contacts_personal_agent.db")

personal_agent = Agent(
    name="Personal Agent",
    id="personal-agent",
    description="A general assistant that can search, calculate and reach specialists.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are a general personal assistant.",
        "Handle everyday questions yourself with your tools.",
        "Contact the news outlet for the latest news and the coding agent for programming work.",
    ],
    tools=[WebSearchTools(), CalculatorTools()],
    contacts=[
        Contact(
            agent=RemoteAgent(base_url="http://localhost:7778", agent_id="news-agent"),
            instructions="Contact to get the latest news from the news outlet",
        ),
        Contact(
            agent=RemoteAgent(
                base_url="http://localhost:7778", agent_id="coding-agent"
            ),
            instructions="Contact for programming work, debugging and GitHub issues or PRs",
        ),
    ],
    markdown=True,
)

agent_os = AgentOS(
    id="personal-agent-os",
    description="Personal agent with remote news and coding contacts",
    agents=[personal_agent],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="04_personal_agent:app", access_log=True, port=7777)
