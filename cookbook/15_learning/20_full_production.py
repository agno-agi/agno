"""
Full Production Agent
===========================================
A complete production-ready agent combining all LearningMachine patterns.

This agent includes:
- User profiles with BACKGROUND extraction
- Session context with planning mode
- Learned knowledge with PROPOSE mode for quality
- GPU-poor optimization (cheap extraction model)
- Multi-user isolation
- Debug tooling
- Interactive CLI

This is the reference implementation for production deployments.
"""

import sys
from datetime import datetime

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
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Configuration
# =============================================================================
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
RESPONSE_MODEL = "gpt-4o"
EXTRACTION_MODEL = "gpt-4o-mini"  # GPU-poor optimization

# =============================================================================
# Setup
# =============================================================================
db = PostgresDb(db_url=DB_URL)

knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=DB_URL, table_name="production_learnings"),
)

# =============================================================================
# Production Instructions
# =============================================================================
INSTRUCTIONS = """\
You are a Production AI Assistant with persistent memory and learning.

## Your Capabilities

1. **Personal Memory**: I remember facts about you across conversations
2. **Session Tracking**: I track our current task's goal, plan, and progress
3. **Accumulated Knowledge**: I learn patterns that help all users
4. **Web Search**: I can find current information

## How I Learn

- **About You**: Automatically extracted from our conversations
- **About Tasks**: Session context tracks what we're working on
- **Reusable Patterns**: I propose learnings for your approval

## When I Propose a Learning

If I discover something valuable and reusable, I'll format it:

---
**💡 Proposed Learning**

**Title:** [concise name]
**Learning:** [the insight]
**Context:** [when to apply]

Save this learning? (yes/no)
---

I only save after you confirm. This ensures quality.

## Commands You Can Use

- "what do you know about me?" - See your profile
- "where are we?" - See session/task context
- "search learnings about X" - Find relevant knowledge
- "debug" - Show system state
"""

# =============================================================================
# Create Production Agent
# =============================================================================
agent = Agent(
    name="Production Assistant",
    model=OpenAIChat(id=RESPONSE_MODEL),
    instructions=INSTRUCTIONS,
    db=db,
    tools=[DuckDuckGoTools()],
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id=EXTRACTION_MODEL),  # Cheap extraction
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            enable_tool=True,  # Agent can also save explicitly
            instructions=(
                "Extract: name, role, company, expertise, preferences, "
                "communication style, current projects"
            ),
        ),
        session_context=SessionContextConfig(
            enable_planning=True,
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,  # Quality control
            enable_search=True,
            enable_save=True,
        ),
    ),
    add_datetime_to_context=True,
    markdown=True,
)


# =============================================================================
# Debug Tools
# =============================================================================
def debug_state(user_id: str, session_id: str):
    """Print current learning state."""
    print("\n" + "=" * 60)
    print("DEBUG: Learning State")
    print("=" * 60)

    # User Profile
    profile = agent.learning.stores["user_profile"].get(user_id=user_id)
    print(f"\n👤 User Profile ({user_id}):")
    if profile and profile.memories:
        for mem in profile.memories:
            print(f"   > {mem.get('content', mem)}")
    else:
        print("   (no profile yet)")

    # Session Context
    context = agent.learning.stores["session_context"].get(session_id=session_id)
    print(f"\n📋 Session Context ({session_id}):")
    if context:
        if context.summary:
            print(f"   Summary: {context.summary[:100]}...")
        if context.goal:
            print(f"   Goal: {context.goal}")
        if context.plan:
            print(f"   Plan: {len(context.plan)} steps")
        if context.progress:
            print(f"   Progress: {len(context.progress)} completed")
    else:
        print("   (no context yet)")

    # Learnings
    results = agent.learning.stores["learned_knowledge"].search(
        query="best practices patterns",
        limit=5,
    )
    print(f"\n📚 Recent Learnings:")
    if results:
        for r in results:
            print(f"   > {getattr(r, 'title', 'Untitled')}")
    else:
        print("   (no learnings yet)")

    print()


# =============================================================================
# Interactive CLI
# =============================================================================
def interactive():
    """Run interactive session."""
    print("=" * 60)
    print("🚀 Production AI Assistant")
    print("=" * 60)
    print(f"""
I'm your AI assistant with persistent memory and learning.

- I remember you across sessions
- I track our current task
- I learn patterns that help everyone

Commands:
  debug  - Show learning state
  clear  - Start new session
  quit   - Exit

Current time: {datetime.now().strftime("%Y-%m-%d %H:%M")}
    """)

    # Default user/session
    user_id = "user@example.com"
    session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M')}"

    print(f"User: {user_id}")
    print(f"Session: {session_id}\n")

    while True:
        try:
            user_input = input("You: ").strip()

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "q"):
                print("\n👋 Goodbye! I'll remember our conversation.")
                break

            if user_input.lower() == "debug":
                debug_state(user_id, session_id)
                continue

            if user_input.lower() == "clear":
                session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                print(f"\n🔄 New session: {session_id}\n")
                continue

            if user_input.lower().startswith("user "):
                user_id = user_input[5:].strip() or "user@example.com"
                print(f"\n👤 Switched to user: {user_id}\n")
                continue

            print()
            agent.print_response(
                user_input,
                user_id=user_id,
                session_id=session_id,
                stream=True,
            )
            print()

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break


# =============================================================================
# Demo Mode
# =============================================================================
def demo():
    """Run demonstration."""
    user_id = "demo_user@example.com"
    session_id = "demo_session"

    print("=" * 60)
    print("Production Agent Demo")
    print("=" * 60)

    # Interaction 1: Introduction
    print("\n--- Introduction ---\n")
    agent.print_response(
        "Hi! I'm Alex, a senior engineer at TechCorp. I work on distributed "
        "systems and prefer detailed, technical explanations with code examples.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    # Interaction 2: Task with planning
    print("\n--- Task with Planning ---\n")
    agent.print_response(
        "I need to design a rate limiting system for our API. Can you help "
        "me think through the approach?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    # Interaction 3: Deep dive (might generate learning)
    print("\n--- Deep Dive ---\n")
    agent.print_response(
        "Let's go with the token bucket approach. What are the key "
        "implementation considerations for a distributed system?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    # If learning was proposed, confirm it
    print("\n--- Confirm Learning (if proposed) ---\n")
    agent.print_response(
        "yes",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    # Show final state
    debug_state(user_id, session_id)


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "demo":
            demo()
        elif sys.argv[1] == "interactive":
            interactive()
        else:
            print(f"Unknown command: {sys.argv[1]}")
            print("Usage: python 20_full_production.py [demo|interactive]")
    else:
        print("=" * 60)
        print("Full Production Agent")
        print("=" * 60)
        print("""
This is a complete production-ready agent with:

✅ User profiles (BACKGROUND extraction)
✅ Session context (planning mode)
✅ Learned knowledge (PROPOSE mode)
✅ GPU-poor optimization
✅ Web search tools
✅ Debug tooling
✅ Interactive CLI

Usage:
  python 20_full_production.py demo        - Run demonstration
  python 20_full_production.py interactive - Interactive chat

Running interactive mode by default...
        """)
        interactive()
