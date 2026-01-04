"""
Team Knowledge Agent
====================
A team-wide knowledge base that learns and shares insights
across team members.

Demonstrates:
- Learned knowledge with team namespace (shared)
- User profiles (individual)
- Global entity memory for team resources

This pattern is ideal for:
- Engineering teams documenting patterns
- Support teams sharing solutions
- Any team building collective intelligence

Run:
    python cookbook/15_learning/patterns/team_knowledge_agent.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearningMachine,
    LearningMode,
    UserProfileConfig,
    LearnedKnowledgeConfig,
    EntityMemoryConfig,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# Shared knowledge base for the team
team_knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="team_knowledge_base",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Team Knowledge Agent
# ============================================================================
team_knowledge_agent = Agent(
    name="Team Knowledge Assistant",
    agent_id="team-knowledge",
    model=model,
    db=db,
    instructions="""\
You are a knowledge management assistant for the engineering team.

Your mission: Help the team capture, organize, and share knowledge
so that insights discovered by one person benefit everyone.

Knowledge types to capture:
- Technical patterns and best practices
- Debugging techniques and solutions
- Architecture decisions and rationale
- Tool configurations and tips
- Lessons learned from incidents

When to save a learning:
- When someone solves a tricky problem
- When a pattern works well (or doesn't)
- When a decision is made with important context
- When a workaround is discovered

For sensitive information:
- Save to entity memory (can be access-controlled)
- Never save credentials or secrets

When answering questions:
- Always search team knowledge first
- Cite sources when applicable
- Suggest related learnings they might find useful
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=team_knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,  # Individual profiles
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="engineering",  # Shared across team
            enable_agent_tools=True,
            agent_can_save=True,
            agent_can_search=True,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="engineering",  # Team-shared entities
            enable_agent_tools=True,
            agent_can_create_entity=True,
            agent_can_search_entities=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo
# ============================================================================
def demo():
    """Demonstrate team knowledge sharing."""
    print("=" * 60)
    print("Team Knowledge Agent Demo")
    print("=" * 60)

    # Engineer 1 shares a learning
    print("\n--- Engineer 1: Shares a solution ---\n")
    team_knowledge_agent.print_response(
        "I just spent 3 hours debugging a weird issue. Turns out when using "
        "Pydantic v2 with FastAPI, you need to use model_dump() instead of "
        "dict(). The old method silently returns wrong data in some edge cases. "
        "Please save this for the team.",
        user_id="alice@company.com",
        session_id="alice_session_1",
        stream=True,
    )

    # Engineer 2 shares another learning
    print("\n--- Engineer 2: Shares a pattern ---\n")
    team_knowledge_agent.print_response(
        "Found a great pattern for handling database migrations: Always create "
        "a new migration for schema changes, never modify existing ones. And "
        "test rollback in staging before applying to production. Save this.",
        user_id="bob@company.com",
        session_id="bob_session_1",
        stream=True,
    )

    # Engineer 3 searches for help
    print("\n--- Engineer 3: Searches for help ---\n")
    team_knowledge_agent.print_response(
        "I'm having issues with Pydantic models not serializing correctly. "
        "Has anyone on the team seen this before?",
        user_id="carol@company.com",
        session_id="carol_session_1",
        stream=True,
    )

    # New engineer looking for patterns
    print("\n--- New Engineer: Looking for patterns ---\n")
    team_knowledge_agent.print_response(
        "I'm new to the team. What are the important patterns and practices "
        "I should know about for our backend work?",
        user_id="dave@company.com",
        session_id="dave_session_1",
        stream=True,
    )


if __name__ == "__main__":
    demo()
