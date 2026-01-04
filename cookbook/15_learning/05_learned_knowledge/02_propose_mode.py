"""
Learned Knowledge: Propose Mode
================================
Agent proposes learnings, user confirms before saving.

In PROPOSE mode, the agent:
1. Identifies valuable insights
2. Proposes them to the user
3. Waits for approval before saving

This gives human quality control over the knowledge base.

Run:
    python cookbook/15_learning/learned_knowledge/02_propose_mode.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# Knowledge base for storing learnings
knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="propose_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Agent with Propose Mode
# ============================================================================
agent = Agent(
    name="Propose Mode Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant that learns from interactions.

When you discover a valuable insight, PROPOSE it to the user:
- Explain what you'd like to save and why
- Ask for explicit confirmation
- Only save after user approval

Format proposals like:
"I'd like to save this insight for future reference:
[Title]: ...
[Learning]: ...
[Why]: This could help with similar tasks.
Should I save this?"

Wait for user to say yes/confirm before using save_learning.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,
            enable_agent_tools=True,
            agent_can_save=True,
            agent_can_search=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Proposal Workflow
# ============================================================================
def demo_proposal_workflow():
    """Show the propose-and-confirm workflow."""
    print("=" * 60)
    print("Demo: Propose and Confirm Workflow")
    print("=" * 60)

    user = "propose_demo@example.com"
    session = "propose_session"

    # Have a conversation that surfaces an insight
    print("\n--- User shares experience ---\n")
    agent.print_response(
        "I just spent 2 hours debugging why my Docker container couldn't "
        "connect to localhost. Turns out you need to use host.docker.internal "
        "on Mac to access the host machine's localhost from inside a container.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Agent should propose saving this
    print("\n💡 The agent should propose saving this insight")
    print("   and wait for user confirmation.")

    # User confirms
    print("\n--- User confirms ---\n")
    agent.print_response(
        "Yes, please save that. It would be helpful for others.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n✅ Learning saved after user approval")


# ============================================================================
# Demo: User Rejects Proposal
# ============================================================================
def demo_rejection():
    """Show handling user rejection."""
    print("\n" + "=" * 60)
    print("Demo: User Rejects Proposal")
    print("=" * 60)

    user = "reject_demo@example.com"
    session = "reject_session"

    print("\n--- User shares something ---\n")
    agent.print_response(
        "I found that restarting my computer fixed the issue.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # User rejects
    print("\n--- User rejects ---\n")
    agent.print_response(
        "No, don't save that. It's not generally useful.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    print("\n✅ Agent respects user's decision not to save")


# ============================================================================
# Demo: Multi-turn Proposal
# ============================================================================
def demo_multi_turn():
    """Show gathering more context before proposing."""
    print("\n" + "=" * 60)
    print("Demo: Multi-turn Proposal")
    print("=" * 60)

    user = "multi_demo@example.com"
    session = "multi_session"

    turns = [
        "I've been optimizing our API response times.",
        "The biggest win was adding Redis caching for user sessions.",
        "It reduced latency from 200ms to 15ms.",
        "The key was caching the entire user object, not just the token.",
    ]

    for turn in turns:
        print(f"\n--- User: {turn[:50]}... ---\n")
        agent.print_response(
            turn,
            user_id=user,
            session_id=session,
            stream=True,
        )

    print("\n--- Confirm the proposal ---\n")
    agent.print_response(
        "Yes, save that optimization insight.",
        user_id=user,
        session_id=session,
        stream=True,
    )


# ============================================================================
# When to Use Propose Mode
# ============================================================================
def when_to_use():
    """Print guidance on when to use PROPOSE mode."""
    print("\n" + "=" * 60)
    print("When to Use PROPOSE Mode")
    print("=" * 60)
    print("""
USE PROPOSE MODE WHEN:
1. Quality matters more than quantity
   - High-stakes knowledge (medical, legal, financial)
   - Shared team knowledge bases

2. User expertise is needed
   - User can judge correctness better than agent
   - Domain-specific insights

3. Trust is still being built
   - New deployments
   - Users want oversight

4. Avoiding noise
   - Prevent low-value learnings
   - Keep knowledge base clean

USE AGENTIC MODE WHEN:
1. Speed matters
   - High-volume interactions
   - User doesn't want friction

2. Agent judgment is trusted
   - Mature deployments
   - Well-prompted agents

3. Insights are clear-cut
   - Technical facts
   - Obvious patterns

COMPARISON:

┌─────────────────┬───────────────┬───────────────┐
│                 │ PROPOSE Mode  │ AGENTIC Mode  │
├─────────────────┼───────────────┼───────────────┤
│ Quality Control │ High (human)  │ Medium (AI)   │
│ User Friction   │ Higher        │ None          │
│ Speed           │ Slower        │ Faster        │
│ Trust Required  │ Low           │ Higher        │
│ Knowledge Vol.  │ Lower, curated│ Higher, noisy │
└─────────────────┴───────────────┴───────────────┘
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_proposal_workflow()
    demo_rejection()
    demo_multi_turn()
    when_to_use()

    print("\n" + "=" * 60)
    print("✅ PROPOSE mode: Human-in-the-loop learning")
    print("   - Agent proposes, user confirms")
    print("   - Higher quality, more user control")
    print("   - Good for sensitive knowledge bases")
    print("=" * 60)
