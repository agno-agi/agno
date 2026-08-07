"""
Local Contacts: an assistant messaging agents and a team on the same AgentOS.

No server needed: all contacts are local entities. The assistant messages a
docs agent and a research team through the message_contact tool; each contact
runs like a child run inside the assistant's session, streaming nested events
into the chat under the contact's own name. Contacts keep their own history,
and the assistant's context stays clean.

Run with: python cookbook/05_agent_os/contacts/02_contacts_local.py
"""

from agno.agent import Agent
from agno.contacts import Contact
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team.team import Team
from agno.tools.websearch import WebSearchTools

db = SqliteDb(id="contacts-local-db", db_file="tmp/contacts_local.db")

# =============================================================================
# Contact Entities
# =============================================================================

docs_agent = Agent(
    name="Docs Agent",
    id="docs-agent",
    description="Writes clear technical documentation.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You write clear, well-structured technical documentation.",
        "Return the finished document in markdown.",
    ],
    markdown=True,
)

web_researcher = Agent(
    name="Web Researcher",
    id="web-researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Search the web and report accurate, sourced findings.",
    tools=[WebSearchTools()],
)

fact_checker = Agent(
    name="Fact Checker",
    id="fact-checker",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Verify claims in the provided material and flag anything questionable.",
)

research_team = Team(
    name="Research Team",
    id="research-team",
    description="Researches topics and fact-checks the findings.",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[web_researcher, fact_checker],
    instructions=[
        "Delegate research to the Web Researcher.",
        "Have the Fact Checker verify the findings.",
        "Reply with the verified research summary.",
    ],
    markdown=True,
    db=db,
)

# =============================================================================
# The Assistant
# =============================================================================

assistant = Agent(
    name="Assistant",
    id="assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=(
        "You are a personal assistant. Use your contacts for specialized work: "
        "research goes to the research team, documentation goes to the docs agent. "
        "Combine their results into your answer."
    ),
    contacts=[
        Contact(agent=docs_agent, instructions="Contact to get documentation written"),
        Contact(
            team=research_team,
            instructions="Contact to research and fact-check a topic",
        ),
    ],
    markdown=True,
)

agent_os = AgentOS(
    id="contacts-local-os",
    description="Assistant with local agent and team contacts",
    agents=[assistant, docs_agent, web_researcher, fact_checker],
    teams=[research_team],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="02_contacts_local:app", access_log=True, port=7777)
