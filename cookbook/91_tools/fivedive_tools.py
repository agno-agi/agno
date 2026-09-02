"""
5dive Tools
=============================

Demonstrates the 5dive toolkit: deploy hosted agents, check fleet status, and file a
Telegram-gated human approval request.

Setup:
    pip install agno
    # Install and authenticate the 5dive CLI first: https://5dive.ai
    #   5dive init
"""

from agno.agent import Agent
from agno.tools.fivedive import FiveDiveTools

# Every tool enabled (the default)
agent = Agent(tools=[FiveDiveTools()])

# Read-only agent: only expose fleet status
readonly_agent = Agent(
    tools=[
        FiveDiveTools(
            enable_fleet_status=True,
            enable_deploy_agent=False,
            enable_request_approval=False,
        )
    ]
)

if __name__ == "__main__":
    readonly_agent.print_response(
        "What agents are currently running in my 5dive fleet?",
        markdown=True,
        stream=True,
    )

    agent.print_response(
        "Deploy a 5dive agent named 'researcher' with the prompt "
        "'Summarize this week's top AI agent papers', then tell me its status.",
        markdown=True,
        stream=True,
    )
