"""
Production: GPU-Poor Learning
=============================
Optimizing learning for cost and latency.

When you can't afford extra LLM calls for background extraction,
use AGENTIC mode with careful tool design.

Strategies:
1. Use AGENTIC mode (no background extraction calls)
2. Smart tool prompting (agent decides when to save)
3. Batch operations (process multiple at once)
4. Smaller models for extraction (when background is needed)

Run:
    python cookbook/15_learning/production/gpu_poor_learning.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Main model for agent responses
main_model = OpenAIResponses(id="gpt-5.2")

# Cheaper model for extraction (if background mode needed)
extraction_model = OpenAIResponses(id="gpt-4.1-mini")  # Faster, cheaper

knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="gpu_poor_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


# ============================================================================
# Strategy 1: Pure AGENTIC Mode (Zero Background Calls)
# ============================================================================
gpu_poor_agent = Agent(
    name="GPU-Poor Learning Agent",
    agent_id="gpu-poor-agent",
    model=main_model,
    db=db,
    instructions="""\
You are a helpful assistant that intelligently manages memory.

IMPORTANT: You control all memory operations. The system does NOT
automatically extract information - you must explicitly save things.

Be selective about what you save:
- Only save information that will be useful in future sessions
- Combine related information into single saves
- Don't save trivial or one-off information

When to use memory tools:
- User shares something they want remembered
- You notice important preferences or context
- Information would significantly improve future interactions

Memory operations are free (no extra cost), but be judicious.
""",
    learning=LearningMachine(
        db=db,
        model=main_model,  # Same model, no extra calls
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.AGENTIC,  # No background extraction
            enable_agent_tools=True,
            agent_can_update_memories=True,
            agent_can_update_profile=True,
        ),
        session_context=SessionContextConfig(
            enable_planning=False,  # Disable to save on extraction
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,  # No background extraction
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Strategy 2: Background with Cheaper Model
# ============================================================================
# If you need background extraction but want to minimize cost,
# use a cheaper model for extraction operations.

cheap_extraction_agent = Agent(
    name="Cheap Extraction Agent",
    model=main_model,  # Main model for responses
    db=db,
    instructions="You are a helpful assistant with automatic memory.",
    learning=LearningMachine(
        db=db,
        model=extraction_model,  # Cheaper model for extraction!
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            # Simpler extraction instructions for cheaper model
            instructions="Extract: name, job, and key preferences. Be brief.",
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: GPU-Poor Agent
# ============================================================================
def demo_gpu_poor():
    """Demonstrate the GPU-poor optimized agent."""
    print("=" * 60)
    print("GPU-Poor Learning Demo")
    print("=" * 60)
    print("""
This agent uses AGENTIC mode exclusively:
- Zero background LLM calls
- Agent decides what to remember
- Same main model for everything
""")

    user = "gpu_poor_demo@example.com"

    # Interaction 1: Agent should save this
    print("\n--- Important info (agent should save) ---\n")
    gpu_poor_agent.print_response(
        "Hi! I'm Taylor, I'm a senior engineer at Netflix. "
        "I prefer detailed technical explanations. Please remember this.",
        user_id=user,
        session_id="gpu_poor_1",
        stream=True,
    )

    # Interaction 2: Trivial (agent should NOT save)
    print("\n--- Trivial question (agent should NOT save) ---\n")
    gpu_poor_agent.print_response(
        "What's 2 + 2?",
        user_id=user,
        session_id="gpu_poor_2",
        stream=True,
    )

    # Interaction 3: Test memory
    print("\n--- Test memory recall ---\n")
    gpu_poor_agent.print_response(
        "What do you remember about me?",
        user_id=user,
        session_id="gpu_poor_3",
        stream=True,
    )


# ============================================================================
# Cost Comparison
# ============================================================================
def cost_comparison():
    """Show cost comparison between strategies."""
    print("\n" + "=" * 60)
    print("Cost Comparison")
    print("=" * 60)
    print("""
Per conversation (assuming 5 turns):

┌─────────────────────────────────────────────────────────────┐
│ Strategy                    │ LLM Calls │ Relative Cost    │
├─────────────────────────────────────────────────────────────┤
│ Full BACKGROUND mode        │ 10        │ 2x (baseline)    │
│ (extraction after each)     │           │                  │
├─────────────────────────────────────────────────────────────┤
│ BACKGROUND + cheap model    │ 10        │ ~1.3x            │
│ (gpt-4o-mini for extraction)│           │                  │
├─────────────────────────────────────────────────────────────┤
│ Pure AGENTIC mode          │ 5         │ 1x (cheapest)    │
│ (agent-controlled saving)   │           │                  │
└─────────────────────────────────────────────────────────────┘

Recommendations:
- High volume + cost sensitive → Pure AGENTIC
- Need auto-extraction + cost sensitive → BACKGROUND + cheap model  
- Quality critical → Full BACKGROUND with main model
""")


# ============================================================================
# Best Practices
# ============================================================================
def best_practices():
    """Print GPU-poor best practices."""
    print("\n" + "=" * 60)
    print("GPU-Poor Best Practices")
    print("=" * 60)
    print("""
1. USE AGENTIC MODE BY DEFAULT
   - No extra LLM calls
   - Agent intelligence for what to save
   - Full control over costs

2. OPTIMIZE TOOL PROMPTS
   - Clear instructions on when to save
   - Emphasize selectivity
   - Combine related information

3. DISABLE PLANNING MODE
   - SessionContext with enable_planning=False
   - Simpler summaries = less extraction

4. IF YOU NEED BACKGROUND:
   - Use cheaper model (gpt-4o-mini)
   - Simpler extraction prompts
   - Consider extraction frequency

5. BATCH OPERATIONS
   - Process multiple users in batch jobs
   - Off-peak extraction
   - Async processing

6. CACHE AGGRESSIVELY
   - Cache user profiles at app level
   - Reduce database reads
   - TTL-based invalidation
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_gpu_poor()
    cost_comparison()
    best_practices()

    print("\n" + "=" * 60)
    print("✅ GPU-Poor Learning: Minimize LLM calls")
    print("   AGENTIC mode = zero background extraction")
    print("   Agent intelligence replaces automatic extraction")
    print("=" * 60)
