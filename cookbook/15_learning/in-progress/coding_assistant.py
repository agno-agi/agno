"""
Pattern: Coding Assistant
=========================
Developer assistant with code style memory and project tracking.

This agent demonstrates:
- User profile for coding preferences and expertise
- Entity memory for tracking projects and codebases
- Learned knowledge for coding patterns and solutions
- Session context for multi-file tasks

Run standalone:
    python cookbook/15_learning/patterns/coding_assistant.py

Or via AgentOS:
    python cookbook/15_learning/run.py
"""

from dataclasses import dataclass, field
from typing import Optional, List

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearningMachine,
    UserProfileConfig,
    SessionContextConfig,
    LearnedKnowledgeConfig,
    EntityMemoryConfig,
    LearningMode,
)
from agno.learn.schemas import UserProfile
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")


# ============================================================================
# Custom Schema: Developer Profile
# ============================================================================
@dataclass
class DeveloperProfile(UserProfile):
    """Extended profile for developers."""

    primary_languages: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Primary programming languages (e.g., Python, TypeScript)"}
    )
    frameworks: Optional[List[str]] = field(
        default=None,
        metadata={"description": "Frameworks used (e.g., FastAPI, React, Django)"}
    )
    editor: Optional[str] = field(
        default=None,
        metadata={"description": "Preferred editor: VS Code | Neovim | PyCharm | other"}
    )
    os: Optional[str] = field(
        default=None,
        metadata={"description": "Operating system: macOS | Linux | Windows"}
    )
    style_preferences: Optional[str] = field(
        default=None,
        metadata={"description": "Code style preferences (type hints, docstrings, etc.)"}
    )
    expertise_level: Optional[str] = field(
        default=None,
        metadata={"description": "Experience level: junior | mid | senior | principal"}
    )
    test_preferences: Optional[str] = field(
        default=None,
        metadata={"description": "Testing preferences (TDD, pytest, jest, etc.)"}
    )


# ============================================================================
# Knowledge Base for Coding Patterns
# ============================================================================
coding_knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="coding_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Coding Assistant
# ============================================================================
coding_assistant = Agent(
    name="Coding Assistant",
    agent_id="coding-assistant",
    model=model,
    db=db,
    instructions="""\
You are an expert coding assistant that adapts to each developer's style.

Your capabilities:
1. **Developer Memory**: Remember coding preferences, languages, and style
2. **Project Tracking**: Track projects, their tech stacks, and conventions
3. **Code Patterns**: Learn and apply reusable coding patterns
4. **Task Context**: Maintain context for multi-file coding tasks

Coding Guidelines:
- Match the developer's style (type hints, docstrings, naming)
- Include tests when the developer prefers them
- Explain at the appropriate level for their expertise
- Reference project conventions when known

When writing code:
- Use their preferred languages/frameworks
- Follow their testing preferences
- Match their formatting style

When you discover a useful pattern:
- Consider saving it as a learning
- Tag it with language/framework for searchability
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=coding_knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            schema=DeveloperProfile,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,  # Helpful for multi-file tasks
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="coding",
            enable_agent_tools=True,
        ),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="user",  # Projects are user-private
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Developer Setup
# ============================================================================
def demo_setup():
    """Show establishing developer preferences."""
    print("=" * 60)
    print("Demo: Coding Assistant - Developer Setup")
    print("=" * 60)

    user = "dev@example.com"
    session = "setup_session"

    print("\n--- Establish preferences ---\n")
    coding_assistant.print_response(
        "Hi! I'm a senior Python developer. I use FastAPI, pytest, and "
        "always write type hints. I prefer comprehensive docstrings and "
        "follow the Google style guide. I use Neovim on macOS. "
        "I always want to see error handling in examples.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Request code
    print("\n--- Request code ---\n")
    coding_assistant.print_response(
        "Write a function to fetch data from an API with retries.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Project Context
# ============================================================================
def demo_project():
    """Show tracking project context."""
    print("\n" + "=" * 60)
    print("Demo: Project Context")
    print("=" * 60)

    user = "dev@example.com"
    session = "project_session"

    # Track project
    print("\n--- Track project ---\n")
    coding_assistant.print_response(
        "I'm working on a project called 'DataPipeline'. It's a FastAPI app "
        "that processes CSV files and stores results in PostgreSQL. "
        "We use SQLAlchemy for ORM and Celery for async tasks. "
        "Track this as a project.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Code in project context
    print("\n--- Code for project ---\n")
    coding_assistant.print_response(
        "Write a Celery task for the DataPipeline project that processes "
        "a CSV file and stores the results.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# Demo: Learning Patterns
# ============================================================================
def demo_patterns():
    """Show learning and applying code patterns."""
    print("\n" + "=" * 60)
    print("Demo: Code Patterns")
    print("=" * 60)

    user = "dev@example.com"
    session = "pattern_session"

    # Save a pattern
    print("\n--- Save a pattern ---\n")
    coding_assistant.print_response(
        "I want to save this pattern: For FastAPI endpoints that make "
        "external API calls, always use httpx with a timeout and wrap in "
        "try/except with proper error responses. This prevents cascading "
        "failures. Save this as a coding pattern.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Apply pattern later
    print("\n--- Apply pattern ---\n")
    coding_assistant.print_response(
        "Write a FastAPI endpoint that calls an external weather API.",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: Style Adaptation
# ============================================================================
def demo_adaptation():
    """Show adapting to different developer styles."""
    print("\n" + "=" * 60)
    print("Demo: Style Adaptation")
    print("=" * 60)

    # Junior developer
    print("\n--- Junior developer ---\n")
    coding_assistant.print_response(
        "I'm new to Python, just learning the basics. Can you show me "
        "how to read a file and count the words?",
        user_id="junior@example.com",
        session_id="junior_session",
        stream=True,
    )

    # Senior developer
    print("\n--- Senior developer ---\n")
    coding_assistant.print_response(
        "I'm a principal engineer. Write an async context manager for "
        "database connection pooling with proper cleanup.",
        user_id="principal@example.com",
        session_id="senior_session",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_setup()
    demo_project()
    demo_patterns()
    demo_adaptation()

    print("\n" + "=" * 60)
    print("✅ Coding Assistant adapts to each developer")
    print("   - Remembers language/framework preferences")
    print("   - Tracks project conventions")
    print("   - Learns reusable patterns")
    print("=" * 60)
