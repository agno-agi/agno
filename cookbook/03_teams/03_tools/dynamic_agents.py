"""
Dynamic Agents
==============

Demonstrates a team that can create specialized agents on demand during execution.

The team leader starts with a single general-purpose member but can spin up
new agents mid-run when it needs expertise that no existing member provides.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create a single starter member
# ---------------------------------------------------------------------------
general_agent = Agent(
    name="General Assistant",
    role="Handle general knowledge questions",
    model=OpenAIResponses(id="gpt-5.4"),
)

# ---------------------------------------------------------------------------
# Create Team with dynamic agent creation enabled
# ---------------------------------------------------------------------------
team = Team(
    name="Dynamic Team",
    mode="coordinate",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[general_agent],
    enable_dynamic_agents=True,
    description="A team that can create specialized agents on demand",
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Ask something that might benefit from a specialist agent
    team.print_response(
        "I need help writing a haiku about the ocean, and also a limerick about a cat. "
        "Create specialized poet agents for each style.",
        stream=True,
    )
