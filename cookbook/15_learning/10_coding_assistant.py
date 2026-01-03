"""
Coding Assistant
===========================================
A coding helper that learns your style and project patterns.

Key Learning Patterns:
- User Profile: Tech stack, code style, experience level
- Session Context: Current task, files being worked on
- Learned Knowledge: Patterns specific to the codebase

Over time, the agent learns:
- Your preferred coding style (tabs vs spaces, naming conventions)
- Project-specific patterns ("we always use X for Y")
- Common solutions to recurring problems
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import (
    LearningMachine,
    LearningMode,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=db_url, table_name="coding_learnings"),
)

# =============================================================================
# Coding Assistant Instructions
# =============================================================================
INSTRUCTIONS = """\
You are a Coding Assistant that learns your style and project patterns.

## Your Approach

1. **Adapt to the user's style**
   - Match their naming conventions
   - Follow their formatting preferences
   - Use frameworks/libraries they prefer

2. **Learn project patterns**
   - Note recurring solutions
   - Remember architecture decisions
   - Track code organization preferences

3. **Provide contextual help**
   - Search learnings before suggesting solutions
   - Reference what's worked before
   - Explain trade-offs based on their experience level

## When to Save Learnings

Save when you discover:
- A project-specific pattern that should be consistent
- A solution to a problem likely to recur
- A best practice the team has adopted

Don't save: One-off fixes, obvious patterns, user-specific preferences (those go in profile).
"""

# =============================================================================
# Create Coding Assistant
# =============================================================================
coding_agent = Agent(
    name="Coding Assistant",
    model=OpenAIChat(id="gpt-4o"),
    instructions=INSTRUCTIONS,
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            instructions=(
                "Focus on: languages used, frameworks preferred, code style, "
                "experience level, current projects"
            ),
        ),
        session_context=SessionContextConfig(
            enable_planning=True,  # Track coding tasks
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helpers
# =============================================================================
def show_developer_profile(user_id: str):
    """Show what we know about a developer."""
    profile = coding_agent.learning.stores["user_profile"].get(user_id=user_id)
    if profile and profile.memories:
        print(f"\n👨‍💻 Developer Profile:")
        for mem in profile.memories:
            print(f"   > {mem.get('content', mem)}")
    print()


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    user_id = "laura@startup.com"

    # --- Session 1: Establish context ---
    print("=" * 60)
    print("Session 1: Developer introduces themselves")
    print("=" * 60)
    coding_agent.print_response(
        "Hi! I'm working on a FastAPI backend. We use SQLAlchemy for ORM, "
        "Pydantic for validation, and pytest for testing. I prefer type hints "
        "everywhere and docstrings in Google style.",
        user_id=user_id,
        session_id="coding_1",
        stream=True,
    )
    show_developer_profile(user_id)

    # --- Session 2: Coding task ---
    print("=" * 60)
    print("Session 2: Coding task")
    print("=" * 60)
    coding_agent.print_response(
        "I need to add a new endpoint for user authentication. "
        "We want to support both JWT and API keys.",
        user_id=user_id,
        session_id="coding_2",
        stream=True,
    )

    # --- Session 3: Pattern emerges ---
    print("=" * 60)
    print("Session 3: Pattern emerges")
    print("=" * 60)
    coding_agent.print_response(
        "We keep having issues with SQLAlchemy sessions in async code. "
        "What's the best pattern for handling this in FastAPI?",
        user_id=user_id,
        session_id="coding_3",
        stream=True,
    )

    # --- Different developer, same codebase ---
    print("=" * 60)
    print("Different Developer: Same codebase")
    print("=" * 60)
    coding_agent.print_response(
        "I just joined the team. How do we handle database sessions "
        "in our FastAPI app?",
        user_id="mike@startup.com",  # New team member
        session_id="coding_4",
        stream=True,
    )

    # --- Show learnings ---
    print("=" * 60)
    print("Accumulated Coding Learnings")
    print("=" * 60)
    results = coding_agent.learning.stores["learned_knowledge"].search(
        query="FastAPI SQLAlchemy async pattern",
        limit=5,
    )
    if results:
        print("\n📚 Coding patterns learned:")
        for r in results:
            title = getattr(r, 'title', 'Untitled')
            print(f"   > {title}")
    else:
        print("\n📚 No coding patterns learned yet")
