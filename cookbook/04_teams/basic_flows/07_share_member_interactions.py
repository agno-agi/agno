"""
This example demonstrates a team where the team leader routes requests to the appropriate member, and the members respond directly to the user.

In addition each team member has access to the shared history of the team.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team


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
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[get_user_profile],
)

technical_support_agent = Agent(
    name="Technical Support Agent",
    role="You are a technical support agent that can answer questions about the technical support.",
    model=OpenAIChat(id="gpt-5-mini"),
)

billing_agent = Agent(
    name="Billing Agent",
    role="You are a billing agent that can answer questions about the billing.",
    model=OpenAIChat(id="gpt-5-mini"),
)


support_team = Team(
    name="Technical Support Team",
    model=OpenAIChat("o3-mini"),
    members=[user_profile_agent, technical_support_agent, billing_agent],
    instructions=[
        "You are a technical support team for a Facebook account that can answer questions about the technical support and billing for Facebook.",
        "Get the user's profile information first if the question is about the user's profile or account.",
    ],
    db=SqliteDb(
        db_file="tmp/technical_support_team.db"
    ),  # Add a database to store the conversation history. This is a requirement for history to work correctly.
    share_member_interactions=True,  # Send member interactions DURING the current run to the other members.
    show_members_responses=True,
)


session_id = f"conversation_{uuid4()}"

## Ask question about technical support
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
