"""
User Profile: Custom Schema
===========================
Extend UserProfile with domain-specific fields.

The base UserProfile has:
- name, preferred_name (built-in)
- memories (list of observations)

You can extend it with typed fields for your domain.
The LLM sees field descriptions and updates them appropriately.

Run:
    python cookbook/15_learning/user_profile/03_custom_schema.py
"""

from dataclasses import dataclass, field
from typing import List, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.learn.schemas import UserProfile
from agno.models.openai import OpenAIChat

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")


# ============================================================================
# Custom Schema: Developer Profile
# ============================================================================
@dataclass
class DeveloperProfile(UserProfile):
    """Extended profile for developers.

    Each field has a description in metadata that the LLM uses
    to understand what information belongs in that field.
    """

    company: Optional[str] = field(
        default=None,
        metadata={"description": "Company or organization they work for"},
    )
    role: Optional[str] = field(
        default=None,
        metadata={
            "description": "Job title or role (e.g., Senior Engineer, Tech Lead)"
        },
    )
    primary_language: Optional[str] = field(
        default=None,
        metadata={"description": "Main programming language they use"},
    )
    languages: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Programming languages they know"},
    )
    frameworks: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Frameworks and libraries they use"},
    )
    experience_years: Optional[int] = field(
        default=None,
        metadata={"description": "Years of programming experience"},
    )
    expertise_level: Optional[str] = field(
        default=None,
        metadata={
            "description": "Technical level: beginner | intermediate | senior | expert"
        },
    )
    preferred_os: Optional[str] = field(
        default=None,
        metadata={"description": "Preferred operating system (macOS, Linux, Windows)"},
    )
    editor: Optional[str] = field(
        default=None,
        metadata={"description": "Preferred code editor or IDE"},
    )


# ============================================================================
# Agent with Custom Schema
# ============================================================================
agent = Agent(
    name="Developer Assistant",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant for software developers.
You remember developer preferences and context to provide tailored help.

When giving code examples, use the developer's preferred language and frameworks.
Adjust technical depth based on their experience level.
""",
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
# Helper: Show profile with custom fields
# ============================================================================
def show_profile(user_id: str) -> None:
    """Display the profile including custom fields."""
    from rich.pretty import pprint

    store = agent.learning.user_profile_store
    profile = store.get(user_id=user_id) if store else None
    if profile:
        print("\n📋 Developer Profile:")
        pprint(profile)
    else:
        print("\n📋 No profile yet")


# ============================================================================
# Demo: Building a Developer Profile
# ============================================================================
def demo_developer_profile():
    """Show custom fields being populated."""
    print("=" * 60)
    print("Demo: Custom Developer Profile")
    print("=" * 60)

    user = "dev@example.com"

    # Introduction with tech context
    print("\n--- Introduction ---\n")
    agent.print_response(
        "Hi! I'm Alex Chen, a senior backend engineer at Stripe. "
        "I've been coding for about 12 years now.",
        user_id=user,
        session_id="custom_1",
        stream=True,
    )
    show_profile(user)

    # Share tech preferences
    print("\n--- Tech stack ---\n")
    agent.print_response(
        "I mainly work with Go and Python. For Python, I use FastAPI "
        "and SQLAlchemy a lot. I'm also familiar with Rust but don't "
        "use it daily. I'm on macOS and live in VS Code.",
        user_id=user,
        session_id="custom_2",
        stream=True,
    )
    show_profile(user)

    # Test personalization
    print("\n--- Test personalized response ---\n")
    agent.print_response(
        "How should I structure a new microservice?",
        user_id=user,
        session_id="custom_3",
        stream=True,
    )


# ============================================================================
# Custom Schema: Customer Support Profile
# ============================================================================
@dataclass
class SupportCustomerProfile(UserProfile):
    """Profile for customer support context."""

    company: Optional[str] = field(
        default=None,
        metadata={"description": "Customer's company name"},
    )
    plan_tier: Optional[str] = field(
        default=None,
        metadata={"description": "Subscription tier: free | pro | enterprise"},
    )
    account_id: Optional[str] = field(
        default=None,
        metadata={"description": "Customer's account ID"},
    )
    products_used: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Which products they actively use"},
    )
    previous_issues: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Summary of past support issues"},
    )
    escalation_history: Optional[bool] = field(
        default=None,
        metadata={"description": "Whether they've escalated issues before"},
    )


# ============================================================================
# Demo: Customer Support Schema
# ============================================================================
def demo_support_profile():
    """Show a different custom schema for support."""
    print("\n" + "=" * 60)
    print("Demo: Customer Support Profile")
    print("=" * 60)

    support_agent = Agent(
        name="Support Agent",
        model=model,
        db=db,
        instructions="You are a customer support agent. Track customer context to provide better support.",
        learning=LearningMachine(
            db=db,
            model=model,
            user_profile=UserProfileConfig(
                mode=LearningMode.BACKGROUND,
                schema=SupportCustomerProfile,
            ),
        ),
        markdown=True,
    )

    user = "support_customer@example.com"

    print("\n--- Customer contact ---\n")
    support_agent.print_response(
        "Hi, I'm having issues with the API. I'm from TechCorp, account ID TC-12345. "
        "We're on the enterprise plan and use the Analytics and Reporting products. "
        "This is the third time I've had API timeout issues this month.",
        user_id=user,
        session_id="support_1",
        stream=True,
    )

    # Show the support-specific profile
    store = support_agent.learning.user_profile_store
    profile = store.get(user_id=user) if store else None
    if profile:
        print("\n📋 Support Customer Profile:")
        from rich.pretty import pprint

        pprint(profile)


# ============================================================================
# Schema Design Guidelines
# ============================================================================
def schema_guidelines():
    """Print guidelines for designing custom schemas."""
    print("\n" + "=" * 60)
    print("Custom Schema Design Guidelines")
    print("=" * 60)
    print("""
1. ALWAYS use Optional[T] for custom fields
   - Fields may not be populated initially
   - Bad:  company: str
   - Good: company: Optional[str] = field(default=None, ...)

2. ALWAYS provide metadata descriptions
   - The LLM uses these to understand what goes in each field
   - Good: metadata={"description": "Their job title"}

3. Use appropriate types
   - str for single values
   - List[str] for multiple values
   - int for counts/years
   - bool for yes/no

4. Keep field names clear and unambiguous
   - Good: primary_language, experience_years
   - Bad: lang, exp

5. Consider your use case
   - What info helps you serve users better?
   - What would be weird to ask for?
   - What changes often vs. stays stable?

Example:
    @dataclass
    class MyProfile(UserProfile):
        company: Optional[str] = field(
            default=None,
            metadata={"description": "Company they work for"}
        )
        skills: Optional[List[str]] = field(
            default=None,
            metadata={"description": "Technical skills and competencies"}
        )
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_developer_profile()
    demo_support_profile()
    schema_guidelines()

    print("\n" + "=" * 60)
    print("✅ Custom schemas extend UserProfile with typed fields")
    print("   - Use field metadata for LLM descriptions")
    print("   - Fields must be Optional with defaults")
    print("   - Design for your specific use case")
    print("=" * 60)
