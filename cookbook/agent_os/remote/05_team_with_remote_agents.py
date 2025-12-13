"""
Examples demonstrating AgentOSRunner for remote execution.

Run `agent_os_setup.py` to start the remote AgentOS instance.
"""

from agno.agent import RemoteAgent
from agno.models.openai import OpenAIChat
from agno.team import Team

team = Team(
    id="world-knowledge-team",
    members=[RemoteAgent(base_url="http://localhost:7778", agent_id="basic-agent")],
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a team that answers questions about the world.",
        "Forward all questions about France to the remote agent.",
    ],
)

team.print_response("What is the capital of France?", stream=True)
