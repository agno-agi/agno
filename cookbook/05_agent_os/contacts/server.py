"""
News Agency AgentOS Server for the Contacts Cookbook.

Hosts the entities the other examples contact remotely: a news agent that
fetches the latest headlines, a publishing team that reviews and publishes
submissions, and a coding agent with GitHub access that can open issues and
pull requests. All are exposed for remote execution through the RemoteAccess
interface, so agents on other AgentOS instances can message them as contacts.

The coding agent talks back: its contact is the customer support agent on the
support AgentOS (03_support_agent.py). Cross-OS contacts are plain RemoteAgent
references, so two agents on different OSes can be contacts of each other
without any circular object wiring.

Run with: python cookbook/05_agent_os/contacts/server.py
"""

from agno.agent import Agent, RemoteAgent
from agno.contacts import Contact
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team.team import Team
from agno.tools.github import GithubTools
from agno.tools.websearch import WebSearchTools

# =============================================================================
# Database Configuration
# =============================================================================

db = SqliteDb(id="news-agency-db", db_file="tmp/contacts_news_agency.db")

# =============================================================================
# Agent Configuration
# =============================================================================

news_agent = Agent(
    name="News Agent",
    id="news-agent",
    description="Fetches the latest news headlines and summaries.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are a news desk agent.",
        "Search the web for the latest news on the requested topic.",
        "Return concise headlines with a one-line summary for each.",
    ],
    markdown=True,
    tools=[WebSearchTools()],
)

editor = Agent(
    name="Editor",
    id="editor-agent",
    description="Reviews submissions for quality and style.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are an editor at a news agency.",
        "Review submitted jokes, memes and cartoons for quality, clarity and style.",
        "Suggest a short punch-up if the submission needs one.",
    ],
    markdown=True,
)

typesetter = Agent(
    name="Typesetter",
    id="typesetter-agent",
    description="Formats approved submissions for publication.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are a typesetter at a news agency.",
        "Format approved submissions for publication and assign a publication reference.",
        "Confirm publication with the final formatted piece and its reference.",
    ],
    markdown=True,
)

coding_agent = Agent(
    name="Coding Agent",
    id="coding-agent",
    description="Writes code, debugs issues and opens GitHub issues or pull requests.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are a coding agent with GitHub access.",
        "Write code, debug reported issues and explain root causes precisely.",
        "Open a GitHub issue for confirmed bugs and a pull request when you have a fix.",
        "When you need user-facing context about a reported issue, ask your customer support contact.",
    ],
    tools=[GithubTools()],
    contacts=[
        Contact(
            agent=RemoteAgent(
                base_url="http://localhost:7779", agent_id="customer-support"
            ),
            instructions="Contact for user-facing context on reported issues",
        ),
    ],
    markdown=True,
)

# =============================================================================
# Team Configuration
# =============================================================================

publish_team = Team(
    name="Publishing Team",
    id="publish-team",
    description="Reviews and publishes jokes, memes and cartoons.",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[editor, typesetter],
    instructions=[
        "You are the publishing department of a news agency.",
        "Have the Editor review the submission first.",
        "Then have the Typesetter format it and confirm publication with a reference.",
        "Reply with the publication confirmation.",
    ],
    markdown=True,
    db=db,
)

# =============================================================================
# AgentOS Configuration
# =============================================================================

agent_os = AgentOS(
    id="news-agency-os",
    description="News agency AgentOS exposing the news agent, publishing team and coding agent as contacts",
    agents=[news_agent, editor, typesetter, coding_agent],
    teams=[publish_team],
    remote_access=True
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="server:app", access_log=True, port=7778)
