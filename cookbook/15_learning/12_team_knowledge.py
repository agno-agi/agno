"""
Team Knowledge Agent
===========================================
An agent that serves a team with shared learnings but individual profiles.

Key Pattern:
- Individual user profiles (Alice ≠ Bob)
- Shared knowledge base (learnings benefit everyone)
- Team-wide insights compound over time

Use case: A team of engineers, analysts, or researchers who want
to capture institutional knowledge while maintaining personal preferences.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import (
    LearningMachine,
    LearningMode,
    LearnedKnowledgeConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Shared knowledge base for the team
team_knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=db_url, table_name="team_knowledge"),
)

# =============================================================================
# Team Agent Instructions
# =============================================================================
INSTRUCTIONS = """\
You are the Team Knowledge Agent for an engineering team.

## Your Role

1. **Individual Preferences**
   - Each team member has their own communication style
   - Adapt to who you're talking to

2. **Shared Knowledge**
   - Insights benefit the whole team
   - Search learnings before answering technical questions
   - Save valuable patterns for future reference

3. **Institutional Memory**
   - Remember project decisions
   - Capture "why we do X" explanations
   - Preserve tribal knowledge

## When to Save Learnings

Save team-wide learnings for:
- Architecture decisions and rationale
- Best practices the team has adopted
- Solutions to problems likely to recur
- "Gotchas" that caught someone

Don't save: Personal preferences (those go in user profile).
"""

# =============================================================================
# Create Team Agent
# =============================================================================
team_agent = Agent(
    name="Team Knowledge Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=INSTRUCTIONS,
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        knowledge=team_knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            instructions="Learn: role, expertise areas, communication preferences",
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
def show_team_member(user_id: str):
    """Show profile for a team member."""
    profile = team_agent.learning.stores["user_profile"].get(user_id=user_id)
    if profile and profile.memories:
        print(f"\n👤 {user_id}:")
        for mem in profile.memories:
            print(f"   > {mem.get('content', mem)}")
    else:
        print(f"\n👤 {user_id}: No profile yet")


def show_team_knowledge():
    """Show shared team knowledge."""
    results = team_agent.learning.stores["learned_knowledge"].search(
        query="engineering team best practices",
        limit=10,
    )
    if results:
        print("\n📚 Team Knowledge Base:")
        for r in results:
            title = getattr(r, 'title', 'Untitled')
            print(f"   > {title}")
    else:
        print("\n📚 No team knowledge yet")
    print()


# =============================================================================
# Demo: Multiple team members
# =============================================================================
if __name__ == "__main__":
    # --- Team Member 1: Senior Engineer ---
    print("=" * 60)
    print("Team Member 1: Senior Engineer (Oscar)")
    print("=" * 60)
    team_agent.print_response(
        "Hi, I'm Oscar, senior backend engineer. I handle most of the database "
        "design decisions. I like detailed technical discussions.",
        user_id="oscar@company.com",
        session_id="oscar_1",
        stream=True,
    )
    show_team_member("oscar@company.com")

    # Oscar contributes knowledge
    print("\n--- Oscar discovers a pattern ---\n")
    team_agent.print_response(
        "We just figured out that our PostgreSQL deadlocks were caused by "
        "inconsistent lock ordering across services. The fix was to always "
        "acquire locks in alphabetical order by table name. Took us 3 days!",
        user_id="oscar@company.com",
        session_id="oscar_2",
        stream=True,
    )

    # --- Team Member 2: Junior Engineer ---
    print("\n" + "=" * 60)
    print("Team Member 2: Junior Engineer (Paula)")
    print("=" * 60)
    team_agent.print_response(
        "Hey! I'm Paula, just joined the team as a junior engineer. "
        "I'm still learning the codebase. Please explain things simply!",
        user_id="paula@company.com",
        session_id="paula_1",
        stream=True,
    )
    show_team_member("paula@company.com")

    # Paula benefits from Oscar's learning
    print("\n--- Paula encounters a similar issue ---\n")
    team_agent.print_response(
        "I'm seeing some database errors about deadlocks. What should I look for?",
        user_id="paula@company.com",
        session_id="paula_2",
        stream=True,
    )

    # --- Team Member 3: Engineering Manager ---
    print("\n" + "=" * 60)
    print("Team Member 3: Engineering Manager (Quinn)")
    print("=" * 60)
    team_agent.print_response(
        "I'm Quinn, the engineering manager. I need high-level summaries "
        "and action items rather than implementation details.",
        user_id="quinn@company.com",
        session_id="quinn_1",
        stream=True,
    )
    show_team_member("quinn@company.com")

    # Quinn asks about the issue
    print("\n--- Quinn reviews the incident ---\n")
    team_agent.print_response(
        "I heard we had some database issues. What happened and what did we learn?",
        user_id="quinn@company.com",
        session_id="quinn_2",
        stream=True,
    )

    # --- Show all profiles and shared knowledge ---
    print("\n" + "=" * 60)
    print("Team Overview")
    print("=" * 60)
    show_team_member("oscar@company.com")
    show_team_member("paula@company.com")
    show_team_member("quinn@company.com")
    show_team_knowledge()
