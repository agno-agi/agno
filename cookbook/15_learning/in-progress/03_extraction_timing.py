"""
Advanced: Extraction Timing
===========================
When does learning extraction happen?

Background extraction can be configured for different timing:
- AFTER (default): Extract after response is sent
- BEFORE: Extract before generating response
- PARALLEL: Extract in parallel with response (future)

Timing trade-offs:
- AFTER: Best UX (faster responses), but context not in current response
- BEFORE: Context available immediately, but adds latency
- PARALLEL: Best of both, but more complex (not yet implemented)

Run:
    python cookbook/15_learning/advanced/03_extraction_timing.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, UserProfileConfig, LearningMode
from agno.learn.config import ExtractionConfig, ExtractionTiming
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")


# ============================================================================
# Agent with AFTER Extraction (Default)
# ============================================================================
after_agent = Agent(
    name="After Extraction Agent",
    model=model,
    db=db,
    instructions="You remember things about users. Extraction happens after your response.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            extraction=ExtractionConfig(
                timing=ExtractionTiming.AFTER,  # Default
            ),
        ),
    ),
    markdown=True,
)


# ============================================================================
# Agent with BEFORE Extraction
# ============================================================================
before_agent = Agent(
    name="Before Extraction Agent",
    model=model,
    db=db,
    instructions="You remember things about users. Extraction happens before your response.",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            extraction=ExtractionConfig(
                timing=ExtractionTiming.BEFORE,
            ),
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: AFTER Timing
# ============================================================================
def demo_after_timing():
    """Demonstrate AFTER extraction timing."""
    print("=" * 60)
    print("Demo: AFTER Extraction Timing (Default)")
    print("=" * 60)
    print("""
Timeline:
1. User sends message
2. Agent generates response (fast)
3. Response sent to user
4. Extraction runs in background

Pros: Fastest response time
Cons: Extracted info not in current response
""")

    user = "after_demo@example.com"

    print("\n--- Same-turn: Info not yet extracted ---\n")
    after_agent.print_response(
        "I'm Alex, I work at Google. What do you know about me?",
        user_id=user,
        session_id="after_1",
        stream=True,
    )

    print("\n--- Next turn: Info now available ---\n")
    after_agent.print_response(
        "What do you know about me now?",
        user_id=user,
        session_id="after_2",
        stream=True,
    )


# ============================================================================
# Demo: BEFORE Timing
# ============================================================================
def demo_before_timing():
    """Demonstrate BEFORE extraction timing."""
    print("\n" + "=" * 60)
    print("Demo: BEFORE Extraction Timing")
    print("=" * 60)
    print("""
Timeline:
1. User sends message
2. Extraction runs first (adds latency)
3. Agent generates response with fresh context
4. Response sent to user

Pros: Extracted info available immediately
Cons: Slower response (extra LLM call)
""")

    user = "before_demo@example.com"

    print("\n--- Same-turn: Info extracted before response ---\n")
    before_agent.print_response(
        "I'm Jordan, I work at Meta. What do you know about me?",
        user_id=user,
        session_id="before_1",
        stream=True,
    )


# ============================================================================
# Timing Decision Guide
# ============================================================================
def timing_guide():
    """Print timing decision guide."""
    print("\n" + "=" * 60)
    print("Extraction Timing Decision Guide")
    print("=" * 60)
    print("""
┌─────────────────────────────────────────────────────────────┐
│ Use AFTER (Default) When:                                   │
├─────────────────────────────────────────────────────────────┤
│ • Response latency is critical                              │
│ • Info doesn't need to be used in same turn                 │
│ • Most conversational use cases                             │
│ • High-volume applications                                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Use BEFORE When:                                            │
├─────────────────────────────────────────────────────────────┤
│ • Context must be in current response                       │
│ • Single-turn interactions (no follow-up expected)          │
│ • Real-time personalization required                        │
│ • Latency is acceptable                                     │
└─────────────────────────────────────────────────────────────┘

Configuration:
```python
UserProfileConfig(
    mode=LearningMode.BACKGROUND,
    extraction=ExtractionConfig(
        timing=ExtractionTiming.AFTER,  # or BEFORE
    ),
)
```
""")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_after_timing()
    demo_before_timing()
    timing_guide()

    print("\n" + "=" * 60)
    print("✅ Extraction timing controls when learning happens")
    print("   AFTER = faster responses (default)")
    print("   BEFORE = immediate context (more latency)")
    print("=" * 60)
