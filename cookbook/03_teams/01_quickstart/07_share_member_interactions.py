"""
Share Member Interactions
=============================

Demonstrates sharing interactions among team members during execution.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
def get_user_profile() -> dict:
    """Get the user profile."""
    return {
        "name": "John Doe",
        "email": "john.doe@example.com",
        "phone": "1234567890",
        "billing_address": "123 Main St, Anytown, USA",
        "login_type": "email",
        "mfa_enabled": True,
    }


user_profile_agent = Agent(
    name="User Profile Agent",
    role="You are a user profile agent that can retrieve information about the user and the user's account.",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[get_user_profile],
)

technical_support_agent = Agent(
    name="Technical Support Agent",
    role="You are a technical support agent that can answer questions about the technical support.",
    model=OpenAIResponses(id="gpt-5.2"),
)

billing_agent = Agent(
    name="Billing Agent",
    role="You are a billing agent that can answer questions about the billing.",
    model=OpenAIResponses(id="gpt-5.2"),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
support_team = Team(
    name="Technical Support Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[user_profile_agent, technical_support_agent, billing_agent],
    instructions=[
        "You are a technical support team for a Facebook account that can answer questions about the technical support and billing for Facebook.",
        "Get the user's profile information first if the question is about the user's profile or account.",
    ],
    db=SqliteDb(
        db_file="tmp/technical_support_team.db"
    ),  # Add a database to store the conversation history.
    share_member_interactions=True,  # Send member interactions during the current run.
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = f"conversation_{uuid4()}"

    # Ask question about technical support
    support_team.print_response(
        "What is my billing address and how do I change it?",
        stream=True,
        session_id=session_id,
    )

    support_team.print_response(
        "Do I have multi-factor enabled? How do I disable it?",
        stream=True,
        session_id=session_id,
    )
