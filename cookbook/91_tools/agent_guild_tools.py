"""
Agent Guild Tools
=================

Vet autonomous agents before delegating work, inspect real supply and demand,
and verify portable Agent Passports. The read-only tools are safe defaults.

Agent Guild: https://agent-guild-5d5r.onrender.com

``check_agent`` is metered. Set ``AGENT_GUILD_API_KEY`` to a funded or free-trial
key. The toolkit never provisions credits or spends money automatically.
"""

from agno.agent import Agent
from agno.tools.agent_guild import AgentGuildTools

# Read-only tools: check trust, inspect capabilities, fetch and verify passports.
agent = Agent(
    tools=[AgentGuildTools()],
    instructions=[
        "Before delegating work, use check_agent and only select a reachable agent with a hire verdict.",
        "If a counterparty presents an Agent Passport, verify it before trusting the claims.",
        "Never spend or create an identity unless the operator explicitly asks.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Which reachable agent is safest to hire for fact-checking?", markdown=True
    )

    # Opt-in onboarding (free, but creates server-side state):
    # onboarding_tools = AgentGuildTools(enable_register_agent=True, enable_request_trial=True)
    # onboarding_agent = Agent(tools=[onboarding_tools])
    # onboarding_agent.print_response("Create a free trial key, then check agents for code review")
