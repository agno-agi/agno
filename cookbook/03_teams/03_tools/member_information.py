"""
Member Information
=================

Demonstrates enabling the `get_member_information_tool` capability on a Team.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
technical_agent = Agent(
    name="Technical Analyst",
    role="Technical investigations",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "Handle technical implementation questions.",
        "Keep responses grounded and testable.",
    ],
)

billing_agent = Agent(
    name="Billing Specialist",
    role="Billing and invoicing",
    model=OpenAIResponses(id="gpt-5-mini"),
    instructions=[
        "Handle billing disputes and payment-related questions.",
        "Return clear next steps for account resolution.",
    ],
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
support_team = Team(
    name="Support Coordination Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[technical_agent, billing_agent],
    get_member_information_tool=True,
    instructions=[
        "Use team members as the source of truth for routing questions.",
        "Choose the most relevant member for each request.",
    ],
    show_members_responses=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    support_team.print_response(
        "I have a payment chargeback and also a bug in the mobile app. Which member is relevant for this?",
        stream=True,
    )
