"""
GPU Poor Learning
===========================================
Optimize costs by using different models for different tasks:

- Cheap model (gpt-4o-mini, gemini-flash): Background extraction
- Expensive model (gpt-4o, claude-sonnet): User-facing responses

This can reduce costs by 10-20x while maintaining quality where it matters.

The key insight: extraction doesn't need the smartest model.
Users only see the response quality, not the extraction quality.
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
    vector_db=PgVector(db_url=db_url, table_name="gpu_poor_learnings"),
)

# =============================================================================
# Model Configuration
# =============================================================================

# Expensive model: For user-facing responses
# This is what users see - worth the cost
RESPONSE_MODEL = OpenAIChat(id="gpt-4o")

# Cheap model: For background extraction
# Users never see this output directly
EXTRACTION_MODEL = OpenAIChat(id="gpt-4o-mini")

# Cost comparison (approximate):
# gpt-4o:      $2.50 / 1M input, $10.00 / 1M output
# gpt-4o-mini: $0.15 / 1M input, $0.60 / 1M output
# Ratio: ~15x cheaper for extraction

# =============================================================================
# Create GPU-Poor Learning Agent
# =============================================================================
agent = Agent(
    model=RESPONSE_MODEL,  # Expensive model for responses
    db=db,
    learning=LearningMachine(
        db=db,
        model=EXTRACTION_MODEL,  # Cheap model for ALL extraction
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            # Uses EXTRACTION_MODEL (cheap)
        ),
        session_context=SessionContextConfig(
            # Uses EXTRACTION_MODEL (cheap)
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.BACKGROUND,
            # Uses EXTRACTION_MODEL (cheap)
        ),
    ),
    markdown=True,
)

# =============================================================================
# Alternative: Per-Store Model Override
# =============================================================================

# If you want different models for different stores:
agent_custom = Agent(
    model=RESPONSE_MODEL,
    db=db,
    learning=LearningMachine(
        db=db,
        model=EXTRACTION_MODEL,  # Default for extraction
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            model=EXTRACTION_MODEL,  # Explicit: cheapest for profiles
        ),
        session_context=SessionContextConfig(
            model=EXTRACTION_MODEL,  # Explicit: cheapest for summaries
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.BACKGROUND,
            model=OpenAIChat(id="gpt-4o"),  # Override: better for insights
        ),
    ),
    markdown=True,
)


# =============================================================================
# Cost Tracking Helper
# =============================================================================
class CostTracker:
    """Simple cost tracker for demonstration."""

    COSTS = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    }

    def __init__(self):
        self.response_tokens = 0
        self.extraction_tokens = 0

    def log_response(self, tokens: int):
        self.response_tokens += tokens

    def log_extraction(self, tokens: int):
        self.extraction_tokens += tokens

    def estimate_cost(self):
        # Rough estimate assuming 50/50 input/output
        response_cost = (self.response_tokens / 1_000_000) * (
            self.COSTS["gpt-4o"]["input"] + self.COSTS["gpt-4o"]["output"]
        ) / 2
        extraction_cost = (self.extraction_tokens / 1_000_000) * (
            self.COSTS["gpt-4o-mini"]["input"] + self.COSTS["gpt-4o-mini"]["output"]
        ) / 2

        return {
            "response_cost": response_cost,
            "extraction_cost": extraction_cost,
            "total": response_cost + extraction_cost,
            "if_all_expensive": (self.response_tokens + self.extraction_tokens)
            / 1_000_000
            * (self.COSTS["gpt-4o"]["input"] + self.COSTS["gpt-4o"]["output"])
            / 2,
        }


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("GPU Poor Learning: Cost Optimization")
    print("=" * 60)
    print(f"""
Configuration:
- Response Model:   {RESPONSE_MODEL.id} (expensive, user-facing)
- Extraction Model: {EXTRACTION_MODEL.id} (cheap, background)

Cost Ratio: ~15x cheaper for extraction tasks
    """)

    user_id = "george@example.com"

    # --- Interaction 1 ---
    print("=" * 60)
    print("Interaction 1: User introduces themselves")
    print("=" * 60)
    print("Response uses: gpt-4o (expensive)")
    print("Extraction uses: gpt-4o-mini (cheap)\n")

    agent.print_response(
        "Hi! I'm George, a machine learning engineer specializing in NLP. "
        "I work at a healthcare startup building medical document processing.",
        user_id=user_id,
        session_id="gpu_poor_1",
        stream=True,
    )

    # --- Interaction 2 ---
    print("\n" + "=" * 60)
    print("Interaction 2: Technical question")
    print("=" * 60)
    agent.print_response(
        "What's the best approach for named entity recognition in medical texts?",
        user_id=user_id,
        session_id="gpu_poor_2",
        stream=True,
    )

    # --- Interaction 3 ---
    print("\n" + "=" * 60)
    print("Interaction 3: Follow-up")
    print("=" * 60)
    agent.print_response(
        "How should I handle abbreviations and acronyms specific to healthcare?",
        user_id=user_id,
        session_id="gpu_poor_3",
        stream=True,
    )

    # --- Cost Analysis ---
    print("\n" + "=" * 60)
    print("Cost Analysis (Illustrative)")
    print("=" * 60)
    print("""
Assume each interaction:
- Response: ~500 tokens
- Extraction: ~300 tokens

3 Interactions:
- Response tokens: 1,500
- Extraction tokens: 900

Cost with GPU-Poor approach:
- Responses (gpt-4o): $0.009
- Extraction (gpt-4o-mini): $0.0003
- Total: ~$0.01

Cost if ALL used gpt-4o:
- Total: ~$0.015

Savings: ~33% on this small example
At scale (millions of interactions): Significant!

Key insight: Users only see response quality.
Background extraction quality doesn't need to be perfect.
    """)

    # Show what was learned
    profile = agent.learning.stores["user_profile"].get(user_id=user_id)
    if profile and profile.memories:
        print("=" * 60)
        print("What was extracted (by cheap model):")
        print("=" * 60)
        for mem in profile.memories:
            print(f"   > {mem.get('content', mem)}")
