"""
Serve a local Team that uses RemoteAgents as members.

This shows how to include agents from another AgentOS server as members in a
local Team, enabling cross-service agent orchestration. The team leader runs
locally and delegates over HTTP to the remote members.

Prerequisites:
1. Start the backing server:
   python cookbook/05_agent_os/remote/server.py

   The server will run on http://localhost:7778

2. Set your OPENAI_API_KEY environment variable

Then run this app and talk to the hybrid team on http://localhost:7777:
   curl -X POST -F "message=Calculate 15 * 23, then summarize what multiplication is." -F "stream=false" http://localhost:7777/teams/hybrid-research-team/runs
"""

from agno.agent import Agent, RemoteAgent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Local Member
# ---------------------------------------------------------------------------

local_summarizer = Agent(
    name="Summarizer",
    role="You synthesize information into clear, concise summaries.",
    model=OpenAIResponses(id="gpt-5.5"),
)

# ---------------------------------------------------------------------------
# Create Remote Members
# ---------------------------------------------------------------------------

remote_assistant = RemoteAgent(
    base_url="http://localhost:7778",
    agent_id="assistant-agent",
)

remote_researcher = RemoteAgent(
    base_url="http://localhost:7778",
    agent_id="researcher-agent",
)

# ---------------------------------------------------------------------------
# Create Team with Local + Remote Members
# ---------------------------------------------------------------------------

hybrid_team = Team(
    name="Hybrid Research Team",
    id="hybrid-research-team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[
        local_summarizer,
        remote_assistant,
        remote_researcher,
    ],
    instructions=[
        "You lead a hybrid team with local and remote agents.",
        "Delegate math questions to the remote Assistant.",
        "Delegate research questions to the remote Researcher.",
        "Use the local Summarizer for final synthesis.",
    ],
    markdown=True,
    show_members_responses=True,
)

agent_os = AgentOS(
    id="hybrid-team-client",
    description="AgentOS serving a local team with remote members",
    teams=[hybrid_team],
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="03_remote_agent_as_team_member:app", reload=True, port=7777)
