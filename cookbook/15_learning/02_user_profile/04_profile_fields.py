"""
User Profile: Working with Profile Fields
=========================================
UserProfile stores structured fields about users.

Profile Fields (structured):
- name, preferred_name (built-in)
- Custom fields from extended schemas

Profile fields are:
- Single, canonical values
- Updated (replaced), not accumulated
- Queryable directly

For unstructured observations that accumulate over time,
use UserMemoryConfig separately.

Run:
    python cookbook/15_learning/02_user_profile/04_profile_fields.py
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
# Custom Schema with Clear Field Separation
# ============================================================================
@dataclass
class WellDesignedProfile(UserProfile):
    """Profile that demonstrates good field design.

    FIELDS should be:
    - Things that have ONE correct answer
    - Things that change via update (not accumulate)
    - Things you'd query directly
    """

    # Good field: Has one canonical answer
    company: Optional[str] = field(
        default=None,
        metadata={"description": "Current employer"},
    )

    # Good field: Updated, not accumulated
    role: Optional[str] = field(
        default=None,
        metadata={"description": "Current job title"},
    )

    # Good field: Single value
    timezone: Optional[str] = field(
        default=None,
        metadata={"description": "User's timezone"},
    )

    # Good field: Enum-like
    expertise_level: Optional[str] = field(
        default=None,
        metadata={"description": "beginner | intermediate | expert"},
    )

    # Good field: List but finite set
    primary_languages: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Main programming languages (top 3-5)"},
    )


# ============================================================================
# Agent
# ============================================================================
agent = Agent(
    name="Profile Fields Demo",
    model=model,
    db=db,
    instructions="""\
You help users understand profile fields.

PROFILE FIELDS: Use for structured, canonical data
- "My name is Sarah" → update name field
- "I work at Google" → update company field
- "Call me Sam" → update preferred_name field
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            schema=WellDesignedProfile,
            enable_agent_tools=True,
            agent_can_update_profile=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Helper
# ============================================================================
def show_profile(user_id: str) -> None:
    """Show profile fields."""
    store = agent.learning.user_profile_store
    profile = store.get(user_id=user_id) if store else None

    if not profile:
        print("\n📋 No profile yet")
        return

    print("\n" + "-" * 40)
    print("📋 PROFILE FIELDS (structured):")
    print("-" * 40)
    print(f"  name: {profile.name}")
    print(f"  preferred_name: {profile.preferred_name}")
    print(f"  company: {getattr(profile, 'company', None)}")
    print(f"  role: {getattr(profile, 'role', None)}")
    print(f"  timezone: {getattr(profile, 'timezone', None)}")
    print(f"  expertise_level: {getattr(profile, 'expertise_level', None)}")
    print(f"  primary_languages: {getattr(profile, 'primary_languages', None)}")


# ============================================================================
# Demo: Field Updates
# ============================================================================
def demo_field_updates():
    """Show information that should go in fields."""
    print("=" * 60)
    print("Demo: Information → Profile Fields")
    print("=" * 60)

    user = "fields_demo@example.com"

    print("\n--- Canonical information (should update fields) ---\n")
    agent.print_response(
        "I'm Alex Chen, I work at Stripe as a Staff Engineer. "
        "I'm an expert in distributed systems. "
        "I'm in the Pacific timezone and mainly use Go and Python.",
        user_id=user,
        session_id="fields_1",
        stream=True,
    )
    show_profile(user)

    print("\n--- Field update (job change) ---\n")
    agent.print_response(
        "Actually, I just moved to a new role at Square.",
        user_id=user,
        session_id="fields_2",
        stream=True,
    )
    show_profile(user)


# ============================================================================
# Decision Guide
# ============================================================================
def decision_guide():
    """Print decision guide for profile fields."""
    print("\n" + "=" * 60)
    print("Decision Guide: What Goes in Profile Fields?")
    print("=" * 60)
    print("""
ASK: Does this have ONE canonical answer?
  YES → Profile Field     "What's their name?" → name field

ASK: Does this get REPLACED or ACCUMULATED?
  REPLACED → Profile Field    "Role changed" → update role field

ASK: Would you query this directly?
  YES → Profile Field     "Show users in Pacific timezone"

ASK: Is this bounded and predictable?
  YES → Profile Field     expertise_level: beginner|intermediate|expert

GOOD PROFILE FIELDS:
  - Name, preferred name
  - Current company, role
  - Timezone, location
  - Skill level (enum)
  - Top programming languages

For unstructured observations that accumulate (like preferences,
current projects, communication style notes), use UserMemoryConfig.
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_field_updates()
    decision_guide()

    print("\n" + "=" * 60)
    print("✅ Key Takeaways:")
    print("   - Profile fields: canonical, replaceable, queryable")
    print("   - Use custom schemas for domain-specific fields")
    print("   - For unstructured observations, use UserMemoryConfig")
    print("=" * 60)
