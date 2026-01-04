"""
User Profile: Agentic Mode
==========================
Agent-driven profile updates via tools.

In AGENTIC mode, the agent decides when to save information using
the `update_user_memory` tool. This gives the agent control over
what gets remembered.

When to use AGENTIC mode:
- When you want the agent to be selective about what it remembers
- When users should be aware that info is being saved
- When you want to avoid background LLM calls

The agent gets a tool called `update_user_memory` that it can call
when it decides something is worth remembering.

Run:
    python cookbook/15_learning/user_profile/02_agentic_mode.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with AGENTIC mode
# ============================================================================
agent = Agent(
    name="Agentic Memory Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant with the ability to remember things about users.

When a user shares something that seems important for future interactions,
use the `update_user_memory` tool to save it. Be selective - only save
things that will genuinely help you assist them better in the future.

Examples of what to save:
- Name and how they prefer to be addressed
- Job role and company
- Technical preferences (languages, frameworks)
- Communication style preferences
- Recurring topics or projects

Don't save:
- Trivial small talk
- One-off questions
- Information that wouldn't help future interactions
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,  # Agent calls tools
            enable_agent_tools=True,  # Expose update_user_memory tool
            agent_can_update_memories=True,
            agent_can_update_profile=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Agent Decides What to Remember
# ============================================================================
def demo_selective_memory():
    """Show agent being selective about what it saves."""
    print("=" * 60)
    print("Demo: Agent Decides What to Remember")
    print("=" * 60)

    user = "agentic_demo@example.com"

    # Important info - should be saved
    print("\n--- Important info (should save) ---\n")
    agent.print_response(
        "I'm Jordan, I'm a DevOps engineer at Netflix. I mostly work with "
        "Kubernetes and Terraform. Please remember this for our future chats.",
        user_id=user,
        session_id="agentic_1",
        stream=True,
    )

    # Trivial question - should NOT be saved
    print("\n--- Trivial question (should not save) ---\n")
    agent.print_response(
        "What's 2 + 2?",
        user_id=user,
        session_id="agentic_2",
        stream=True,
    )

    # Preference worth saving
    print("\n--- Preference (should save) ---\n")
    agent.print_response(
        "By the way, I really prefer YAML over JSON for configuration. "
        "And I like verbose output with clear explanations.",
        user_id=user,
        session_id="agentic_3",
        stream=True,
    )

    # Check what was saved
    print("\n--- Memory check ---\n")
    agent.print_response(
        "What do you remember about me?",
        user_id=user,
        session_id="agentic_4",
        stream=True,
    )


# ============================================================================
# Demo: Explicit Save Request
# ============================================================================
def demo_explicit_save():
    """Show user explicitly asking agent to remember something."""
    print("\n" + "=" * 60)
    print("Demo: Explicit Save Request")
    print("=" * 60)

    user = "explicit_save@example.com"

    print("\n--- Explicit request ---\n")
    agent.print_response(
        "Please remember: I always want you to include test examples "
        "when you write code for me. This is very important.",
        user_id=user,
        session_id="explicit_1",
        stream=True,
    )

    print("\n--- Later conversation ---\n")
    agent.print_response(
        "Write me a function to validate email addresses.",
        user_id=user,
        session_id="explicit_2",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_selective_memory()
    demo_explicit_save()

    print("\n" + "=" * 60)
    print("✅ In AGENTIC mode, the agent controls what gets remembered")
    print("   The update_user_memory tool lets it save selectively.")
    print("=" * 60)
