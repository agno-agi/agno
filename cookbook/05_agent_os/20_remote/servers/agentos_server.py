"""
Serve Agents, a Team, and a Workflow for Remote* examples
=========================================================

This AgentOS is the native-protocol backend for the remote curriculum. It is
public by default; set OS_SECURITY_KEY before startup to require a Bearer
credential for the authenticated RemoteAgent example.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/20_remote/servers/agentos_server.py
Try: fetch GET http://127.0.0.1:7780/config
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings
from agno.team import Team
from agno.tools.calculator import CalculatorTools
from agno.workflow import Step, Workflow

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="remote-agentos-db",
    db_file="tmp/remote_agentos.db",
)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

assistant = Agent(
    id="assistant-agent",
    name="Remote Assistant",
    description="A remote assistant with exact arithmetic tools.",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "Answer clearly and concisely.",
        "Use the calculator for arithmetic.",
    ],
    tools=[CalculatorTools()],
    markdown=True,
)

researcher = Agent(
    id="researcher-agent",
    name="Remote Researcher",
    description="A remote specialist that explains technical concepts.",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "Explain technical concepts from established knowledge.",
        "Do not claim to have searched external sources.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

research_team = Team(
    id="research-team",
    name="Remote Research Team",
    description="A remote Team that coordinates calculation and explanation.",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[assistant, researcher],
    instructions=[
        "Delegate arithmetic to the Remote Assistant.",
        "Delegate conceptual explanations to the Remote Researcher.",
        "Return one concise combined answer.",
    ],
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------

qa_workflow = Workflow(
    id="qa-workflow",
    name="Remote QA Workflow",
    description="A one-step remote Workflow backed by the assistant.",
    steps=[
        Step(
            name="Answer Question",
            agent=assistant,
        )
    ],
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="remote-agentos",
    name="Remote AgentOS",
    description="Native AgentOS backend for RemoteAgent, RemoteTeam, and RemoteWorkflow.",
    db=db,
    agents=[assistant, researcher],
    teams=[research_team],
    workflows=[qa_workflow],
    settings=AgnoAPISettings(os_security_key=os.getenv("OS_SECURITY_KEY")),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7780)
