"""
Learned Knowledge: Search and Apply
====================================
Using stored learnings to improve responses.

This demonstrates:
- Searching the knowledge base for relevant learnings
- Applying learnings to enhance responses
- The recall → context flow

Run:
    python cookbook/15_learning/learned_knowledge/04_search_and_apply.py
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
        table_name="search_apply_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ============================================================================
# Agent with Search Capability
# ============================================================================
agent = Agent(
    name="Knowledge-Applied Agent",
    model=model,
    db=db,
    instructions="""\
You are a helpful assistant with access to prior learnings.

When answering questions:
1. Search your learnings for relevant insights
2. Apply any relevant learnings to your response
3. Cite the learning if it significantly shapes your answer

Your knowledge base contains insights from previous conversations.
Use them to give better, more informed responses.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
            agent_can_save=True,
            agent_can_search=True,  # Key: enables search tool
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Populate Knowledge Base
# ============================================================================
def demo_populate():
    """Seed the knowledge base with learnings."""
    print("=" * 60)
    print("Demo: Populating Knowledge Base")
    print("=" * 60)

    user = "seed@example.com"

    learnings = [
        (
            "Save this: When setting up PostgreSQL for high availability, "
            "always configure synchronous_commit to 'on' for the primary. "
            "Using 'off' risks data loss on failover."
        ),
        (
            "Save this: For Python web apps, Gunicorn workers should be "
            "set to (2 * CPU cores) + 1 for CPU-bound work, or higher for "
            "I/O-bound work."
        ),
        (
            "Save this: When debugging memory leaks in Node.js, use the "
            "--inspect flag with Chrome DevTools. The heap snapshot "
            "comparison feature finds leaks quickly."
        ),
        (
            "Save this: For rate limiting APIs, use token bucket algorithm "
            "for smooth throttling. Leaky bucket is better for strict limits."
        ),
    ]

    for i, learning in enumerate(learnings, 1):
        print(f"\n--- Saving learning {i} ---\n")
        agent.print_response(
            learning,
            user_id=user,
            session_id=f"seed_{i}",
            stream=True,
        )

    print("\n✅ Knowledge base populated with 4 learnings")


# ============================================================================
# Demo: Search and Apply
# ============================================================================
def demo_search_apply():
    """Show searching and applying learnings."""
    print("\n" + "=" * 60)
    print("Demo: Search and Apply Learnings")
    print("=" * 60)

    user = "apply@example.com"

    questions = [
        (
            "I'm setting up PostgreSQL for a critical application. "
            "What should I know about failover safety?"
        ),
        (
            "How many Gunicorn workers should I configure for my "
            "Flask app on a 4-core server?"
        ),
        ("My Node.js app's memory keeps growing. How can I find where the leak is?"),
    ]

    for i, question in enumerate(questions, 1):
        print(f"\n--- Question {i} ---\n")
        print(f"User: {question}\n")
        agent.print_response(
            question,
            user_id=user,
            session_id=f"apply_{i}",
            stream=True,
        )
        print("\n" + "-" * 40)
        print("🔍 Agent searched learnings and applied relevant insights")


# ============================================================================
# Demo: No Relevant Learnings
# ============================================================================
def demo_no_match():
    """Show behavior when no learnings match."""
    print("\n" + "=" * 60)
    print("Demo: No Relevant Learnings Found")
    print("=" * 60)

    user = "nomatch@example.com"

    print("\n--- Question with no matching learnings ---\n")
    agent.print_response(
        "What's a good recipe for chocolate chip cookies?",
        user_id=user,
        session_id="nomatch_1",
        stream=True,
    )

    print("\n💡 Agent answers normally when no learnings are relevant")


# ============================================================================
# Demo: Manual Search Tool
# ============================================================================
def demo_manual_search():
    """Show explicit search requests."""
    print("\n" + "=" * 60)
    print("Demo: Explicit Search Request")
    print("=" * 60)

    user = "manual@example.com"

    print("\n--- User explicitly asks to search ---\n")
    agent.print_response(
        "Search your learnings for anything about rate limiting.",
        user_id=user,
        session_id="manual_1",
        stream=True,
    )


# ============================================================================
# How Context Injection Works
# ============================================================================
def explain_context_flow():
    """Explain how learnings become context."""
    print("\n" + "=" * 60)
    print("How Context Injection Works")
    print("=" * 60)
    print("""
THE RECALL → CONTEXT FLOW:

1. User sends message
   ↓
2. LearningMachine.recall(message=...)
   - Embeds the message
   - Searches vector DB for similar learnings
   - Returns top-k matches
   ↓
3. LearningMachine.build_context(learnings)
   - Formats learnings as XML
   - Injects into system prompt
   ↓
4. Agent sees context like:

   <learnings>
   Here are relevant learnings from previous conversations:

   1. **PostgreSQL Failover Safety**
      Always configure synchronous_commit to 'on' for primary.
      Using 'off' risks data loss on failover.
      _Context: High availability setup_

   2. **Gunicorn Worker Count**
      Set to (2 * CPU cores) + 1 for CPU-bound work.
      _Context: Python web app deployment_

   Apply these learnings when relevant to the current task.
   </learnings>

   ↓
5. Agent responds with knowledge applied


SEARCH vs RECALL:

┌───────────────────┬────────────────────────────────────┐
│ Method            │ Purpose                            │
├───────────────────┼────────────────────────────────────┤
│ recall()          │ Automatic, runs before response    │
│                   │ Returns learnings for context      │
├───────────────────┼────────────────────────────────────┤
│ search_learnings  │ Agent tool, explicit search        │
│ (tool)            │ User can ask agent to search       │
└───────────────────┴────────────────────────────────────┘

Both use the same vector search, but:
- recall() is automatic and adds to system prompt
- search_learnings is agent-controlled and returns inline
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_populate()
    demo_search_apply()
    demo_no_match()
    demo_manual_search()
    explain_context_flow()

    print("\n" + "=" * 60)
    print("✅ Search and Apply: Using learnings effectively")
    print("   - Automatic recall injects context")
    print("   - search_learnings tool for explicit search")
    print("   - Vector similarity finds relevant learnings")
    print("=" * 60)
