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
First-time founder raising seed round. Initial rejections -> pattern
recognition -> pitch pivot -> success. Shows how learning accumulates
to improve fundraising outcomes.
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

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

fundraising_kb = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="fundraising_kb",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


def create_fundraising_assistant(founder_id: str, session_id: str) -> Agent:
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
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            user_memory=UserMemoryConfig(
                mode=LearningMode.ALWAYS,
            ),
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,
                # Scoped per founder so investor notes don't leak
                namespace=f"fundraising:{founder_id}",
                enable_agent_tools=True,
            ),
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace=f"fundraising:{founder_id}:patterns",
            ),
        ),
        user_id=founder_id,
        session_id=session_id,
        markdown=True,
    )


if __name__ == "__main__":
    founder_id = "sarah@startup.com"

    # Single agent for the entire fundraising journey
    assistant = create_fundraising_assistant(founder_id, "seed-round")

    # Week 1: Initial outreach
    print("\n" + "=" * 60)
    print("WEEK 1: Initial Outreach")
    print("=" * 60 + "\n")

    assistant.print_response(
        "Hi! I'm Sarah, founding a B2B AI SaaS startup focused on data quality for ML. "
        "This is my first time fundraising and I'm targeting seed stage investors.",
        stream=True,
    )
    assistant.learning_machine.user_profile_store.print(user_id=founder_id)

    assistant.print_response(
        "I just pitched Sequoia (early stage AI investor). They asked a lot about our data moat.",
        stream=True,
    )

    assistant.print_response(
        "Meeting with a16z tomorrow. They focus on infrastructure and dev tools.",
        stream=True,
    )

    assistant.print_response(
        "Also reaching out to Benchmark - they're known for product-led growth companies.",
        stream=True,
    )
    assistant.learning_machine.session_context_store.print(session_id="seed-round")

    # Week 2: First rejections
    print("\n" + "=" * 60)
    print("WEEK 2: First Rejections")
    print("=" * 60 + "\n")

    assistant.print_response(
        "Sequoia passed. They said we're too early - come back with more traction.",
        stream=True,
    )

    assistant.print_response(
        "a16z also passed. They wanted to see a bigger TAM.",
        stream=True,
    )

    assistant.print_response(
        "Benchmark asked for a demo but I only showed slides. What patterns do you see?",
        stream=True,
    )
    assistant.learning_machine.session_context_store.print(session_id="seed-round")

    # Week 3: Pivot based on learning
    print("\n" + "=" * 60)
    print("WEEK 3: Pitch Pivot")
    print("=" * 60 + "\n")

    assistant.print_response(
        "I'm adjusting my approach. Leading with product demo instead of slides. "
        "Emphasizing our proprietary dataset as the data moat.",
        stream=True,
    )
    assistant.learning_machine.learned_knowledge_store.print(query="demo")

    assistant.print_response(
        "Targeting FirstRound - they focus on dev tools.",
        stream=True,
    )

    assistant.print_response(
        "Also pitching Unusual Ventures (AI/data focus) and Insight Partners (vertical SaaS).",
        stream=True,
    )
    assistant.learning_machine.session_context_store.print(session_id="seed-round")

    # Week 4: Improved results
    print("\n" + "=" * 60)
    print("WEEK 4: Second Meetings")
    print("=" * 60 + "\n")

    assistant.print_response(
        "Demo-first approach is working! FirstRound wants a second meeting with partners.",
        stream=True,
    )

    assistant.print_response(
        "Unusual Ventures loved the data moat story. They're asking about unit economics.",
        stream=True,
    )

    assistant.print_response(
        "Insight wants to meet our early customers. How do we convert these to term sheets?",
        stream=True,
    )
    assistant.learning_machine.session_context_store.print(session_id="seed-round")

    # Week 5: Close round
    print("\n" + "=" * 60)
    print("WEEK 5: Term Sheet & Close")
    print("=" * 60 + "\n")

    assistant.print_response(
        "FirstRound gave us a term sheet! $2M at $10M post-money valuation.",
        stream=True,
    )

    assistant.print_response(
        "Reflecting on what worked: demo-first approach, emphasizing data moat, "
        "fast follow-up (< 24 hours), and bringing customer references to second meetings.",
        stream=True,
    )
    assistant.learning_machine.learned_knowledge_store.print(query="successful")

    assistant.print_response(
        "We accepted FirstRound's term sheet. Seed round closed!",
        stream=True,
    )
    assistant.learning_machine.session_context_store.print(session_id="seed-round")

    # Verify all 5 stores
    print("\n" + "=" * 60)
    print("VERIFICATION: All 5 Stores")
    print("=" * 60 + "\n")

    assistant.learning_machine.user_profile_store.print(user_id=founder_id)
    assistant.learning_machine.session_context_store.print(session_id="seed-round")
    assistant.learning_machine.learned_knowledge_store.print(query="fundraising")

    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60 + "\n")
    print("Week 1-2: 3 pitches, 0 term sheets (slide decks)")
    print("Week 3-5: 3 pitches, 1 CLOSE at $2M (demo-first + data moat)")
    print("\nClosed seed round through pattern recognition!")
