"""
User Profile: Memory vs Fields
==============================
When to use structured fields vs unstructured memories.

UserProfile has two types of data:

1. **Profile Fields** (structured)
   - Typed fields like `name`, `preferred_name`, custom fields
   - Good for: Concrete, queryable facts
   - Updated via: `update_profile` tool or BACKGROUND extraction

2. **Memories** (unstructured)
   - List of observations, preferences, context
   - Good for: Nuanced, varied information
   - Updated via: `add_memory`, `update_memory`, `delete_memory`

This cookbook shows when to use each.

Run:
    python cookbook/15_learning/user_profile/04_memory_vs_fields.py
"""

from dataclasses import dataclass, field
from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.learn.schemas import UserProfile
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")


# ============================================================================
# Schema with Both Fields and Memories
# ============================================================================
@dataclass
class HybridProfile(UserProfile):
    """Profile with structured fields for queryable data.

    Fields are good for:
    - Data you might filter/query on
    - Data with a clear structure
    - Data that rarely changes

    Memories are good for:
    - Observations that don't fit a field
    - Context that varies in structure
    - Nuanced preferences
    """

    # FIELDS: Structured, queryable
    company: Optional[str] = field(
        default=None, metadata={"description": "Company name"}
    )
    role: Optional[str] = field(
        default=None, metadata={"description": "Job title or role"}
    )
    timezone: Optional[str] = field(
        default=None, metadata={"description": "Timezone (e.g., America/New_York)"}
    )
    expertise_level: Optional[str] = field(
        default=None, metadata={"description": "beginner | intermediate | expert"}
    )

    # MEMORIES: Inherited from UserProfile
    # - memories: List[Dict] for unstructured observations


# ============================================================================
# Agent with Hybrid Profile
# ============================================================================
agent = Agent(
    name="Hybrid Profile Agent",
    model=model,
    db=db,
    instructions="""\
You help users and remember important information about them.

When deciding what to remember:
- Use PROFILE FIELDS for concrete facts (company, role, timezone, expertise)
- Use MEMORIES for preferences, context, and observations that don't fit fields

Examples:
- "I work at Google" → Update `company` field
- "I prefer verbose explanations with examples" → Add as a memory
- "I'm a senior engineer" → Update `role` field
- "I hate when code has no comments" → Add as a memory
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,
            schema=HybridProfile,
            enable_agent_tools=True,
            agent_can_update_memories=True,
            agent_can_update_profile=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Fields vs Memories
# ============================================================================
def demo_fields_vs_memories():
    """Show when each type is used."""
    print("=" * 60)
    print("Demo: Fields vs Memories")
    print("=" * 60)

    user = "hybrid_demo@example.com"

    # Mix of field-appropriate and memory-appropriate info
    print("\n--- Mixed information ---\n")
    agent.print_response(
        "I'm a senior backend engineer at Stripe, based in Pacific time. "
        "I'm an expert-level developer. "
        "I prefer concise responses without fluff. "
        "I always want to see error handling in code examples. "
        "Please remember all this.",
        user_id=user,
        session_id="hybrid_1",
        stream=True,
    )

    print("\n--- Check what was saved where ---\n")
    agent.print_response(
        "What do you know about me? Distinguish between structured profile data "
        "and general observations/memories.",
        user_id=user,
        session_id="hybrid_2",
        stream=True,
    )


# ============================================================================
# Demo: When to Use Each
# ============================================================================
def demo_decision_guide():
    """Show the decision process for fields vs memories."""
    print("\n" + "=" * 60)
    print("Decision Guide: Fields vs Memories")
    print("=" * 60)

    print("""
┌─────────────────────────────────────────────────────────────┐
│ USE PROFILE FIELDS FOR:                                     │
├─────────────────────────────────────────────────────────────┤
│ ✓ Concrete, single-value facts                              │
│   - Name, company, role, timezone                           │
│ ✓ Data you might filter or query on                         │
│   - "Show me all enterprise users"                          │
│ ✓ Data with clear, consistent structure                     │
│   - expertise_level: "beginner | intermediate | expert"     │
│ ✓ Data that changes infrequently                            │
│   - Company name (changes rarely)                           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ USE MEMORIES FOR:                                           │
├─────────────────────────────────────────────────────────────┤
│ ✓ Preferences and style                                     │
│   - "Prefers verbose explanations"                          │
│ ✓ Context that doesn't fit a field                          │
│   - "Working on a migration from Django to FastAPI"         │
│ ✓ Observations that vary in structure                       │
│   - "Has trouble with async/await concepts"                 │
│ ✓ Multiple related facts                                    │
│   - "Likes Python, learning Rust, avoids JavaScript"        │
│ ✓ Temporary or evolving information                         │
│   - "Currently debugging a memory leak"                     │
└─────────────────────────────────────────────────────────────┘
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_decision_guide()
    demo_fields_vs_memories()

    print("\n" + "=" * 60)
    print("✅ Use fields for structured, queryable facts")
    print("   Use memories for everything else")
    print("=" * 60)
