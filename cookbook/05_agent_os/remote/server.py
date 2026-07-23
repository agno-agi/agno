"""
AgentOS Server for Remote Cookbook Examples.

This server hosts the agents and team that the other examples in this folder
consume through RemoteAgent and RemoteTeam.

Remote execution is opt-in: only the entities passed to the RemoteAccess interface
are remotely callable. The internal agent below is registered on the AgentOS but
NOT passed to the RemoteAccess interface, so it is served on the default API but
cannot be executed remotely. Workflows are not remotely executable: the QA workflow
is served on this AgentOS via the standard workflow API only.

Run with: python cookbook/05_agent_os/remote/server.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.remote_access import RemoteAccess
from agno.team.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# =============================================================================
# Database Configuration
# =============================================================================

db = SqliteDb(id="remote-cookbook-db", db_file="tmp/remote_cookbook.db")

# =============================================================================
# Agent Configuration
# =============================================================================

# Agent 1: Assistant with calculator tools (exposed for remote execution)
assistant = Agent(
    name="Assistant",
    id="assistant-agent",
    description="A helpful AI assistant with calculator capabilities.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are a helpful AI assistant.",
        "Use the calculator tool for any math operations.",
    ],
    markdown=True,
    tools=[CalculatorTools()],
)

# Agent 2: Researcher with web search capabilities (exposed for remote execution)
researcher = Agent(
    name="Researcher",
    id="researcher-agent",
    description="A research assistant with web search capabilities.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=[
        "You are a research assistant.",
        "Search the web for information when needed.",
        "Provide well-researched, accurate responses.",
    ],
    markdown=True,
    tools=[WebSearchTools()],
)

# Agent 3: Internal agent (NOT exposed for remote execution)
internal_agent = Agent(
    name="Internal Agent",
    id="internal-agent",
    description="An internal agent that is not remotely callable.",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=["You are an internal assistant for local use only."],
    markdown=True,
)

# =============================================================================
# Team Configuration
# =============================================================================

research_team = Team(
    name="Research Team",
    id="research-team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[assistant, researcher],
    instructions=[
        "You are a research team that coordinates multiple specialists.",
        "Delegate math questions to the Assistant.",
        "Delegate research questions to the Researcher.",
        "Combine insights from team members for comprehensive answers.",
    ],
    markdown=True,
    db=db,
)

# =============================================================================
# Workflow Configuration
# =============================================================================

qa_workflow = Workflow(
    name="QA Workflow",
    description="A simple Q&A workflow that uses the assistant agent",
    id="qa-workflow",
    db=db,
    steps=[
        Step(
            name="Answer Question",
            agent=assistant,
        ),
    ],
)

# =============================================================================
# AgentOS Configuration
# =============================================================================

agent_os = AgentOS(
    id="remote-cookbook-server",
    description="AgentOS server exposing entities for the remote cookbook examples",
    agents=[assistant, researcher, internal_agent],
    teams=[research_team],
    workflows=[qa_workflow],
    interfaces=[
        # Opt-in remote execution: internal_agent is deliberately left out, so it is
        # not reachable via /remote even though it is served on the default API.
        RemoteAccess(
            agents=[assistant, researcher],
            teams=[research_team],
        ),
    ],
)

# FastAPI app instance (for uvicorn)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="server:app", access_log=True, port=7778)
