"""
Pattern: Startup Fundraising Assistant (ALL 5 Stores)
====================================================
A founder uses AI assistant over 5 weeks to close seed round.

This cookbook demonstrates:
1. UserProfile - Founder background, experience
2. UserMemory - Communication style, decision patterns
3. SessionContext - Current round progress tracking
4. EntityMemory - Investors, meetings, feedback
5. LearnedKnowledge - Pitch patterns that work

Scenario:
First-time founder raising seed round. Initial rejections → pattern
recognition → pitch pivot → success. Shows how learning accumulates
to improve fundraising outcomes.

Success metrics:
- Before learning: 12 pitches → 1 second meeting → 0 term sheets
- After learning: 8 pitches → 4 second meetings → 2 term sheets → 1 close
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Knowledge base for fundraising patterns
fundraising_kb = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="fundraising_kb",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


def create_fundraising_assistant(founder_id: str, session_id: str) -> Agent:
    """Create fundraising assistant with all 5 learning stores."""
    return Agent(
        model=OpenAIResponses(id="gpt-4o"),
        db=db,
        instructions="""\
You are a fundraising assistant helping founders raise capital.

CAPABILITIES:
- Track founder's style and preferences
- Manage investor pipeline (entities)
- Learn patterns from pitch feedback
- Maintain session context for current round

WORKFLOW:
- Search for similar investors before recommending outreach
- Track meeting outcomes as events on investor entities
- Save successful pitch patterns as learnings
- Suggest next steps based on pipeline status

Be supportive and data-driven in your recommendations.""",
        learning=LearningMachine(
            knowledge=fundraising_kb,
            # UserProfile: Founder background, experience
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            # UserMemory: Communication style, stress patterns
            user_memory=UserMemoryConfig(
                mode=LearningMode.ALWAYS,
            ),
            # SessionContext: Round progress tracking
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            # EntityMemory: Investors, meetings, feedback
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,
                namespace="fundraising:seed",
                enable_agent_tools=True,
            ),
            # LearnedKnowledge: Pitch patterns that work
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace="fundraising:patterns",
            ),
        ),
        user_id=founder_id,
        session_id=session_id,
        markdown=True,
    )


# ============================================================================
# Demo: 5-Week Fundraising Journey
# ============================================================================

if __name__ == "__main__":
    # Seed knowledge base with fundraising best practices from authoritative sources
    fundraising_kb.add_content(
        url="https://www.ycombinator.com/library/2u-how-to-build-your-seed-round-pitch-deck",
        skip_if_exists=True,
    )

    founder_id = "sarah@startup.com"

    # Week 1: Initial outreach
    print("\n" + "=" * 60)
    print("WEEK 1: Initial Outreach")
    print("=" * 60 + "\n")

    intro = create_fundraising_assistant(founder_id, "seed-round")
    intro.print_response(
        "Hi! I'm Sarah, founding a B2B AI SaaS startup focused on data quality for ML. "
        "This is my first time fundraising and I'm targeting seed stage investors.",
        stream=True,
    )
    intro.get_learning_machine().user_profile_store.print(user_id=founder_id)

    sequoia_pitch = create_fundraising_assistant(founder_id, "seed-round")
    sequoia_pitch.print_response(
        "I just pitched Sequoia (early stage AI investor). They asked a lot about our data moat.",
        stream=True,
    )

    a16z_meeting = create_fundraising_assistant(founder_id, "seed-round")
    a16z_meeting.print_response(
        "Meeting with a16z tomorrow. They focus on infrastructure and dev tools.",
        stream=True,
    )

    benchmark_outreach = create_fundraising_assistant(founder_id, "seed-round")
    benchmark_outreach.print_response(
        "Also reaching out to Benchmark - they're known for product-led growth companies.",
        stream=True,
    )
    benchmark_outreach.get_learning_machine().session_context_store.print(
        session_id="seed-round"
    )

    # Week 2: First rejections
    print("\n" + "=" * 60)
    print("WEEK 2: First Rejections")
    print("=" * 60 + "\n")

    sequoia_reject = create_fundraising_assistant(founder_id, "seed-round")
    sequoia_reject.print_response(
        "Sequoia passed. They said we're too early - come back with more traction.",
        stream=True,
    )

    a16z_reject = create_fundraising_assistant(founder_id, "seed-round")
    a16z_reject.print_response(
        "a16z also passed. They wanted to see a bigger TAM.",
        stream=True,
    )

    benchmark_feedback = create_fundraising_assistant(founder_id, "seed-round")
    benchmark_feedback.print_response(
        "Benchmark asked for a demo but I only showed slides. What patterns do you see?",
        stream=True,
    )
    benchmark_feedback.get_learning_machine().session_context_store.print(
        session_id="seed-round"
    )

    # Week 3: Pivot based on learning
    print("\n" + "=" * 60)
    print("WEEK 3: Pitch Pivot")
    print("=" * 60 + "\n")

    pivot_strategy = create_fundraising_assistant(founder_id, "seed-round")
    pivot_strategy.print_response(
        "I'm adjusting my approach. Leading with product demo instead of slides. "
        "Emphasizing our proprietary dataset as the data moat.",
        stream=True,
    )
    pivot_strategy.get_learning_machine().learned_knowledge_store.print(query="demo")

    firstround_pitch = create_fundraising_assistant(founder_id, "seed-round")
    firstround_pitch.print_response(
        "Targeting FirstRound - they focus on dev tools.",
        stream=True,
    )

    unusual_insight_pitch = create_fundraising_assistant(founder_id, "seed-round")
    unusual_insight_pitch.print_response(
        "Also pitching Unusual Ventures (AI/data focus) and Insight Partners (vertical SaaS).",
        stream=True,
    )
    unusual_insight_pitch.get_learning_machine().session_context_store.print(
        session_id="seed-round"
    )

    # Week 4: Improved results
    print("\n" + "=" * 60)
    print("WEEK 4: Second Meetings")
    print("=" * 60 + "\n")

    firstround_second = create_fundraising_assistant(founder_id, "seed-round")
    firstround_second.print_response(
        "Demo-first approach is working! FirstRound wants a second meeting with partners.",
        stream=True,
    )

    unusual_interest = create_fundraising_assistant(founder_id, "seed-round")
    unusual_interest.print_response(
        "Unusual Ventures loved the data moat story. They're asking about unit economics.",
        stream=True,
    )

    insight_customers = create_fundraising_assistant(founder_id, "seed-round")
    insight_customers.print_response(
        "Insight wants to meet our early customers. How do we convert these to term sheets?",
        stream=True,
    )
    insight_customers.get_learning_machine().session_context_store.print(
        session_id="seed-round"
    )

    # Week 5: Close round
    print("\n" + "=" * 60)
    print("WEEK 5: Term Sheet & Close")
    print("=" * 60 + "\n")

    term_sheet_received = create_fundraising_assistant(founder_id, "seed-round")
    term_sheet_received.print_response(
        "FirstRound gave us a term sheet! $2M at $10M post-money valuation.",
        stream=True,
    )

    reflect_on_learnings = create_fundraising_assistant(founder_id, "seed-round")
    reflect_on_learnings.print_response(
        "Reflecting on what worked: demo-first approach, emphasizing data moat, "
        "fast follow-up (< 24 hours), and bringing customer references to second meetings.",
        stream=True,
    )
    reflect_on_learnings.get_learning_machine().learned_knowledge_store.print(
        query="successful"
    )

    round_closed = create_fundraising_assistant(founder_id, "seed-round")
    round_closed.print_response(
        "We accepted FirstRound's term sheet. Seed round closed!",
        stream=True,
    )
    round_closed.get_learning_machine().session_context_store.print(
        session_id="seed-round"
    )

    # Verify all 5 stores have data
    print("\n" + "=" * 60)
    print("VERIFICATION: All 5 Stores")
    print("=" * 60 + "\n")

    round_closed.get_learning_machine().user_profile_store.print(user_id=founder_id)
    round_closed.get_learning_machine().session_context_store.print(
        session_id="seed-round"
    )
    round_closed.get_learning_machine().learned_knowledge_store.print(
        query="fundraising"
    )

    # Success metrics
    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60 + "\n")
    print("Week 1-2: 3 pitches, 0 term sheets (slide decks)")
    print("Week 3-5: 3 pitches, 1 CLOSE at $2M (demo-first + data moat)")
    print("\nClosed seed round through pattern recognition!")
