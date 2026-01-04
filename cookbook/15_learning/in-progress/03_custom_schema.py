"""
User Profile: Custom Schema
===========================
Extend UserProfile with typed fields for your domain.

The base UserProfile has:
- name: User's full name
- preferred_name: How they like to be addressed
- memories: List of unstructured observations

You can extend it with custom fields that the LLM will recognize
and update appropriately. Use field metadata to provide descriptions
that guide the extraction.

Run:
    python cookbook/15_learning/user_profile/03_custom_schema.py
"""

from dataclasses import dataclass, field
from typing import Optional, List

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig, LearningMode
from agno.learn.schemas import UserProfile
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")


# ============================================================================
# Custom Schema: Customer Support Profile
# ============================================================================
@dataclass
class SupportProfile(UserProfile):
    """Extended user profile for customer support agents.
    
    The LLM sees field descriptions and updates them when mentioned
    in conversation. This provides structured data alongside memories.
    """

    company: Optional[str] = field(
        default=None,
        metadata={"description": "Company or organization the user works for"}
    )
    plan_tier: Optional[str] = field(
        default=None,
        metadata={"description": "Subscription tier: free | pro | enterprise"}
    )
    timezone: Optional[str] = field(
        default=None,
        metadata={"description": "User's timezone (e.g., America/New_York, Europe/London)"}
    )
    expertise_level: Optional[str] = field(
        default=None,
        metadata={"description": "Technical level: beginner | intermediate | expert"}
    )
    primary_language: Optional[str] = field(
        default=None,
        metadata={"description": "Primary programming language they use"}
    )
    integrations: Optional[List[str]] = field(
        default=None,
        metadata={"description": "List of integrations or tools they use with our product"}
    )


# ============================================================================
# Custom Schema: Developer Profile
# ============================================================================
@dataclass
class DeveloperProfile(UserProfile):
    """Extended user profile for coding assistants."""

    github_username: Optional[str] = field(
        default=None,
        metadata={"description": "GitHub username"}
    )
    primary_languages: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Programming languages they use most (e.g., Python, TypeScript)"}
    )
    frameworks: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Frameworks they work with (e.g., FastAPI, React, Django)"}
    )
    editor: Optional[str] = field(
        default=None,
        metadata={"description": "Preferred code editor (e.g., VS Code, Neovim, PyCharm)"}
    )
    os: Optional[str] = field(
        default=None,
        metadata={"description": "Operating system: macOS | Linux | Windows"}
    )
    style_preferences: Optional[str] = field(
        default=None,
        metadata={"description": "Coding style preferences (e.g., type hints, docstrings, tests)"}
    )


# ============================================================================
# Support Agent with Custom Schema
# ============================================================================
support_agent = Agent(
    name="Support Agent",
    model=model,
    db=db,
    instructions="You are a customer support agent. Help users with their questions.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            schema=SupportProfile,  # Use custom schema
        ),
    ),
    markdown=True,
)


# ============================================================================
# Developer Assistant with Custom Schema
# ============================================================================
dev_agent = Agent(
    name="Dev Assistant",
    model=model,
    db=db,
    instructions="You are a coding assistant. Help developers write better code.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            schema=DeveloperProfile,  # Use custom schema
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Support Profile
# ============================================================================
def demo_support_profile():
    """Show structured extraction with SupportProfile."""
    print("=" * 60)
    print("Demo: Support Profile Schema")
    print("=" * 60)

    user = "support_schema_demo@example.com"

    print("\n--- Customer introduces themselves ---\n")
    support_agent.print_response(
        "Hi, I'm Alex from TechCorp. We're on the enterprise plan. "
        "I'm pretty technical - been a developer for 10 years. "
        "I mainly use Python and we've integrated with Slack and Jira. "
        "I'm in the Pacific timezone.",
        user_id=user,
        session_id="support_1",
        stream=True,
    )

    print("\n--- Check extracted profile ---\n")
    support_agent.print_response(
        "What do you know about me and my account?",
        user_id=user,
        session_id="support_2",
        stream=True,
    )


# ============================================================================
# Demo: Developer Profile
# ============================================================================
def demo_developer_profile():
    """Show structured extraction with DeveloperProfile."""
    print("\n" + "=" * 60)
    print("Demo: Developer Profile Schema")
    print("=" * 60)

    user = "dev_schema_demo@example.com"

    print("\n--- Developer introduces themselves ---\n")
    dev_agent.print_response(
        "Hey! I'm @codemaster on GitHub. I write mostly Python and TypeScript. "
        "I use FastAPI for backends and Next.js for frontends. "
        "Neovim is my editor of choice, running on Arch Linux btw. "
        "I'm a stickler for type hints and I always write tests first (TDD).",
        user_id=user,
        session_id="dev_1",
        stream=True,
    )

    print("\n--- Ask for code ---\n")
    dev_agent.print_response(
        "Write me a function to fetch data from an API.",
        user_id=user,
        session_id="dev_2",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_support_profile()
    demo_developer_profile()

    print("\n" + "=" * 60)
    print("✅ Custom schemas give you structured fields alongside memories")
    print("   Field descriptions guide the LLM on what to extract.")
    print("=" * 60)
