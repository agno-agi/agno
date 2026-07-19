"""
Agent OS - Web Interface for Your Agents
=========================================
This file starts an Agent OS server that provides a web interface for all
the agents, teams, and workflows in this Quick Start guide.

What is Agent OS?
-----------------
Agent OS is Agno's runtime that lets you:
- Chat with your agents through a beautiful web UI
- Explore session history
- Monitor traces and debug agent behavior
- Manage knowledge bases and memories
- Switch between agents, teams, and workflows

How to Use
----------
1. Start the server:
   python cookbook/00_quickstart/run.py

2. Visit https://os.agno.com in your browser

3. Add your local endpoint: http://localhost:7777

4. Select any agent, team, or workflow and start chatting

Prerequisites
-------------
- All agents from this quick start are registered automatically
- For the knowledge agent, load the knowledge base first:
  python cookbook/00_quickstart/agent_search_over_knowledge.py

Learn More
----------
- Agent OS Overview: https://docs.agno.com/agent-os/overview
- Agno Documentation: https://docs.agno.com
"""

from pathlib import Path

from agent_search_over_knowledge import agent_with_knowledge
from agent_with_guardrails import agent_with_guardrails
from agent_with_memory import agent_with_memory
from agent_with_state_management import agent_with_state_management
from agent_with_storage import agent_with_storage
from agent_with_structured_output import agent_with_structured_output
from agent_with_tools import agent_with_tools
from agent_with_typed_input_output import agent_with_typed_input_output
from agno.os import AgentOS
from custom_tool_for_self_learning import self_learning_agent
from human_in_the_loop import human_in_the_loop_agent
from multi_agent_team import multi_agent_team
from sequential_workflow import sequential_workflow

# ---------------------------------------------------------------------------
# AgentOS Config
# ---------------------------------------------------------------------------
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="Quick Start AgentOS",
    agents=[
        agent_with_tools,
        agent_with_storage,
        agent_with_knowledge,
        self_learning_agent,
        agent_with_structured_output,
        agent_with_typed_input_output,
        agent_with_memory,
        agent_with_state_management,
        human_in_the_loop_agent,
        agent_with_guardrails,
    ],
    teams=[multi_agent_team],
    workflows=[sequential_workflow],
    config=config_path,
    tracing=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
