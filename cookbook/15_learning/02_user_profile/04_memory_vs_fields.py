"""
User Profile: Memory vs Fields
==============================
When to use profile fields vs. unstructured memories.

UserProfile has two types of data:

1. **Profile Fields** (structured)
   - name, preferred_name, custom fields
   - Single, canonical values
   - Updated via update_profile tool

2. **Memories** (unstructured)
   - List of observations
   - Accumulate over time
   - For info that doesn't fit fields

This cookbook helps you choose the right approach.

Run:
    python cookbook/15_learning/user_profile/04_memory_vs_fields.py
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
# Custom Schema with Clear Separation
# ============================================================================
@dataclass
class WellDesignedProfile(UserProfile):
    """Profile that demonstrates good field vs memory separation.

    FIELDS (single canonical values):
    - Things that have ONE correct answer
    - Things that change via update (not accumulate)
    - Things you'd query directly

    MEMORIES (observations):
    - Things that accumulate over time
    - Context that doesn't fit a field
    - One-off details
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

    # Note: The following would be BAD as fields, good as memories:
    # - "project_history": Accumulates, unbounded
    # - "conversation_topics": Too varied
    # - "random_facts": No structure


# ============================================================================
# Agent
# ============================================================================
agent = Agent(
    name="Memory vs Fields Demo",
    model=model,
    db=db,
    instructions="""\
You help users understand the difference between profile fields and memories.

PROFILE FIELDS: Use for structured, canonical data
- "My name is Sarah" → update name field
- "I work at Google" → update company field
- "Call me Sam" → update preferred_name field

MEMORIES: Use for observations and context
- "Had a great time at the conference" → add memory
- "Working on a machine learning project" → add memory
- "Prefers morning meetings" → add memory

When unsure, memories are safer (more flexible).
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            schema=WellDesignedProfile,
            enable_agent_tools=True,
            agent_can_update_profile=True,
            agent_can_update_memories=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Helper
# ============================================================================
def show_profile(user_id: str) -> None:
    """Show profile with fields and memories separated."""
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

    print("\n" + "-" * 40)
    print("📝 MEMORIES (unstructured):")
    print("-" * 40)
    if profile.memories:
        for mem in profile.memories:
            content = (
                mem.get("content", str(mem)) if isinstance(mem, dict) else str(mem)
            )
            print(f"  - {content}")
    else:
        print("  (none)")


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
# Demo: Memory Observations
# ============================================================================
def demo_memory_observations():
    """Show information that should go in memories."""
    print("\n" + "=" * 60)
    print("Demo: Information → Memories")
    print("=" * 60)

    user = "memories_demo@example.com"

    print("\n--- Contextual observations (should be memories) ---\n")
    agent.print_response(
        "I'm Jamie. I've been dealing with a really tricky performance bug "
        "in our caching layer for the past week. We're using Redis but "
        "considering switching to Memcached. Oh, and I have a standup "
        "every day at 9am so I prefer calls after 10.",
        user_id=user,
        session_id="memories_1",
        stream=True,
    )
    show_profile(user)

    print("\n🔍 Notice:")
    print("   - Name → field (canonical)")
    print("   - Performance bug → memory (current project)")
    print("   - Redis/Memcached → memory (current context)")
    print("   - Meeting preference → memory (behavioral observation)")


# ============================================================================
# Decision Guide
# ============================================================================
def decision_guide():
    """Print decision guide for fields vs memories."""
    print("\n" + "=" * 60)
    print("Decision Guide: Field or Memory?")
    print("=" * 60)
    print("""
ASK: Does this have ONE canonical answer?
  YES → Field     "What's their name?" → name field
  NO  → Memory    "What are they working on?" → memory

ASK: Does this get REPLACED or ACCUMULATED?
  REPLACED → Field    "Role changed" → update role field
  ACCUMULATED → Memory "Another project" → add memory

ASK: Would you query this directly?
  YES → Field     "Show users in Pacific timezone"
  NO  → Memory    "Show users who like morning meetings"

ASK: Is this bounded and predictable?
  YES → Field     expertise_level: beginner|intermediate|expert
  NO  → Memory    "Prefers verbose explanations with examples"

EXAMPLES:

✅ FIELDS (update):
  - Name, preferred name
  - Current company, role
  - Timezone, location
  - Skill level (enum)
  - Top programming languages

📝 MEMORIES (accumulate):
  - Current projects
  - Preferences and quirks
  - Past experiences
  - Communication style notes
  - Random facts shared

⚠️ GRAY AREA (could be either):
  - "Uses Python" → Field if tracking top languages
  - "Learning Python" → Memory (current activity)
  - "Expert in Python" → Field (expertise_level)
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_field_updates()
    demo_memory_observations()
    decision_guide()

    print("\n" + "=" * 60)
    print("✅ Key Takeaways:")
    print("   - Fields: canonical, replaceable, queryable")
    print("   - Memories: contextual, accumulated, flexible")
    print("   - When unsure, memories are safer")
    print("=" * 60)
