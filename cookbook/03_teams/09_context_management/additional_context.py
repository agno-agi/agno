"""
Additional Context
=================

Demonstrates adding custom `additional_context` and resolving placeholders at
run time through Team context resolution.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
ops_agent = Agent(
    name="Ops Copilot",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "Follow operational policy and include ownership guidance.",
    ],
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
policy_team = Team(
    name="Policy Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[ops_agent],
    additional_context=(
        "The requester is a {role} in the {region}. Use language suitable for an "
        "internal process update and include owner + timeline whenever possible."
    ),
    resolve_in_context=True,
    dependencies={"role": "support lead", "region": "EMEA"},
    instructions=["Answer as a practical operational policy assistant."],
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    policy_team.print_response(
        "A partner asked for a temporary extension on compliance docs.",
        stream=True,
    )
