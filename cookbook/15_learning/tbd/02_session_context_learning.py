"""
Session Context Learning — Track Conversation State
====================================================
Session context summarizes what's happening in the current session.
Useful for long conversations, planning workflows, or multi-step tasks.

This is opt-in because it adds an extra LLM call after each conversation
to extract/update the session summary.

What you get with session_context=True:
- ✅ User Profile: Remembers facts about users (default)
- ✅ Session Context: Summarizes current session state

With enable_planning=True, also tracks:
- Goal: What the user is trying to accomplish
- Plan: Steps to achieve the goal
- Progress: Which steps are done

Run this example:
    python cookbook/learning/02_session_context_learning.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine
from agno.learn.config import SessionContextConfig
from agno.models.openai import OpenAIChat

# =============================================================================
# Setup
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Database for storing profiles and session context
db = PostgresDb(db_url=db_url)

# Model for the agent
model = OpenAIChat(id="gpt-4o")

# =============================================================================
# Agent with Session Context (Basic)
# =============================================================================

basic_agent = Agent(
    name="Assistant with Context",
    model=model,
    db=db,
    # Opt-in to session context
    learning=LearningMachine(session_context=True),
    add_datetime_to_context=True,
    markdown=True,
)

# =============================================================================
# Agent with Planning Mode
# =============================================================================

planning_agent = Agent(
    name="Planning Assistant",
    model=model,
    db=db,
    # Enable planning to track goal/plan/progress
    learning=LearningMachine(
        session_context=SessionContextConfig(enable_planning=True),
    ),
    add_datetime_to_context=True,
    markdown=True,
)


# =============================================================================
# Demo: Basic Session Context
# =============================================================================


def demo_basic_context():
    """Show basic session summarization."""
    print("=" * 60)
    print("Demo: Basic Session Context")
    print("=" * 60)

    user_id = "developer@example.com"
    session_id = "debug_session"

    print("\n📝 Message 1: Describe a problem")
    print("-" * 40)

    basic_agent.print_response(
        "I'm getting a weird error in my Python code. When I try to import "
        "pandas, it says 'ModuleNotFoundError' but I'm sure I installed it.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n\n📝 Message 2: Add more context")
    print("-" * 40)

    basic_agent.print_response(
        "I'm using a virtual environment. I activated it with 'source venv/bin/activate'.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n\n📝 Message 3: Ask for summary")
    print("-" * 40)

    basic_agent.print_response(
        "Can you summarize what we've figured out so far?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n\n💡 Session context captures the debugging journey,")
    print("   even if the conversation history gets long.")


def demo_planning_mode():
    """Show planning mode with goal/plan/progress tracking."""
    print("\n" + "=" * 60)
    print("Demo: Planning Mode (Goal/Plan/Progress)")
    print("=" * 60)

    user_id = "builder@example.com"
    session_id = "project_planning"

    print("\n📝 Message 1: Define a goal")
    print("-" * 40)

    planning_agent.print_response(
        "I want to build a REST API for a todo app. Can you help me plan this out?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n\n📝 Message 2: Start implementing")
    print("-" * 40)

    planning_agent.print_response(
        "Great plan! I've set up the project structure and installed FastAPI. "
        "What's next?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n\n📝 Message 3: Check progress")
    print("-" * 40)

    planning_agent.print_response(
        "Where are we in the plan? What's left to do?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    print("\n\n💡 Planning mode tracks:")
    print("   - Goal: Build a REST API for a todo app")
    print("   - Plan: The steps we outlined")
    print("   - Progress: What's been completed")


def demo_long_conversation():
    """Show how session context helps with long conversations."""
    print("\n" + "=" * 60)
    print("Demo: Long Conversation Context")
    print("=" * 60)

    user_id = "researcher@example.com"
    session_id = "research_session"

    messages = [
        "I'm researching machine learning frameworks for a new project.",
        "We need something that works well with time series data.",
        "The team is mostly familiar with Python, some know R.",
        "Performance is critical - we're processing millions of data points.",
        "We also need good visualization capabilities.",
        "What would you recommend given everything we've discussed?",
    ]

    for i, msg in enumerate(messages, 1):
        print(f"\n📝 Message {i}")
        print("-" * 40)

        basic_agent.print_response(
            msg,
            user_id=user_id,
            session_id=session_id,
            stream=True,
        )

    print("\n\n💡 Session context summarizes all requirements,")
    print("   making the final recommendation well-informed.")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import sys

    demos = {
        "basic": demo_basic_context,
        "planning": demo_planning_mode,
        "long": demo_long_conversation,
    }

    if len(sys.argv) > 1:
        demo_name = sys.argv[1]

        if demo_name == "all":
            demo_basic_context()
            demo_planning_mode()
            demo_long_conversation()
        elif demo_name in demos:
            demos[demo_name]()
        else:
            print(f"Unknown demo: {demo_name}")
            print(f"Available: {', '.join(demos.keys())}, all")
    else:
        print("=" * 60)
        print("🧠 Session Context Learning — Track Conversation State")
        print("=" * 60)
        print("\nThis cookbook shows session_context=True in action.")
        print("\nAvailable demos:")
        print("  basic    - Basic session summarization")
        print("  planning - Goal/plan/progress tracking")
        print("  long     - Long conversation context")
        print("  all      - Run all demos")
        print("\nUsage: python 02_session_context_learning.py <demo>")
        print("\nRunning 'basic' demo by default...\n")
        demo_basic_context()
