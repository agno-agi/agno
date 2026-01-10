"""
Combined Learning: User Profile + Session Context

Most agents benefit from combining user profiles with session context.
This gives you both long-term user knowledge AND short-term conversation
tracking.

Key concepts:
- User profile persists across all sessions
- Session context is per-conversation
- Both work together automatically
- Different extraction triggers and timings

Run: python -m cookbook.combined.01_user_plus_session
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode
from agno.learn.config import SessionContextConfig, UserProfileConfig
from agno.models.openai import OpenAIChat

# Database URL - use environment variable in production
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# BASIC COMBINED SETUP
# =============================================================================


def create_combined_agent(user_id: str, session_id: str) -> Agent:
    """Create agent with both user profile and session context."""
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        learning=LearningMachine(
            db=db,
            # Long-term: learns about the user over time
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            # Short-term: tracks this conversation
            session_context=SessionContextConfig(
                enable_planning=True,  # Also track goals/progress
            ),
        ),
        user_id=user_id,
        session_id=session_id,
        markdown=True,
    )


def demo_new_user_new_session():
    """First interaction with a new user."""
    print("\n" + "=" * 60)
    print("NEW USER, NEW SESSION")
    print("=" * 60)

    _agent = create_combined_agent(user_id="new_user_123", session_id="session_001")

    print("""
    Scenario: First-time user, first conversation
    
    User Profile: Empty (nothing learned yet)
    Session Context: Empty (conversation just started)
    
    As conversation progresses:
    - Session context captures what's discussed THIS conversation
    - User profile extracts facts about the user for FUTURE conversations
    """)

    # Simulate a conversation
    messages = [
        "Hi! I'm Alex, a data scientist at TechCorp. I need help with a ML pipeline.",
        "I primarily use Python and have about 5 years of experience.",
        "The pipeline processes customer data for churn prediction.",
    ]

    print("\n    Simulated conversation:")
    for msg in messages:
        print(f"    User: {msg}")

    print("""
    After this conversation:
    
    SESSION CONTEXT captures:
    - Summary: "User is building ML churn prediction pipeline"
    - Goal: "Help with ML pipeline for customer churn"
    - Progress: "Gathered requirements, identified Python stack"
    
    USER PROFILE learns (for future sessions):
    - Name: Alex
    - Role: Data scientist at TechCorp
    - Skills: Python, ML, 5 years experience
    """)


def demo_returning_user_new_session():
    """Returning user starts a new conversation."""
    print("\n" + "=" * 60)
    print("RETURNING USER, NEW SESSION")
    print("=" * 60)

    _agent = create_combined_agent(
        user_id="alex_456",  # Same user
        session_id="session_002",  # New session
    )

    print("""
    Scenario: Alex returns for a new conversation

    User Profile: Loaded with previously learned info
    - Name: Alex
    - Role: Data scientist at TechCorp
    - Skills: Python, ML
    
    Session Context: Fresh (new conversation)
    - No summary yet
    - No goals yet
    
    The agent knows WHO Alex is, but not what THIS conversation is about.
    """)

    messages = [
        "Hey, I'm back! Now I need help with model deployment.",
        "We're considering AWS SageMaker vs Kubernetes.",
    ]

    print("\n    Simulated conversation:")
    for msg in messages:
        print(f"    User: {msg}")

    print("""
    Agent can leverage user profile:
    "Since you're using Python and have ML experience, both options
     work well. SageMaker is simpler, K8s gives more control..."
    
    Session context tracks THIS conversation:
    - Summary: "Discussing ML model deployment options"
    - Goal: "Help choose between SageMaker and Kubernetes"
    """)


def demo_same_session_continuation():
    """Continuing the same session after interruption."""
    print("\n" + "=" * 60)
    print("SAME USER, SAME SESSION (Continuation)")
    print("=" * 60)

    _agent = create_combined_agent(
        user_id="alex_456",
        session_id="session_002",  # Same session as before
    )

    print("""
    Scenario: Alex continues the same conversation (after a break)

    User Profile: Still has all learned info
    Session Context: Restored from previous messages
    - Summary: "Discussing ML model deployment"
    - Goal: "Choose between SageMaker and Kubernetes"
    - Progress: "Reviewed both options"
    
    Even if early messages were truncated, session context preserves
    the conversation state!
    """)


# =============================================================================
# DATA FLOW VISUALIZATION
# =============================================================================


def show_data_flow():
    """Visualize how data flows between stores."""
    print("\n" + "=" * 60)
    print("DATA FLOW: USER PROFILE vs SESSION CONTEXT")
    print("=" * 60)

    print("""
    
    ┌─────────────────────────────────────────────────────────────────┐
    │                    CONVERSATION                                  │
    │  User: "I'm Alex, a data scientist working on churn prediction" │
    └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
    ┌─────────────────────┐         ┌─────────────────────┐
    │   USER PROFILE      │         │   SESSION CONTEXT   │
    │                     │         │                     │
    │ Extracts:           │         │ Captures:           │
    │ • name: "Alex"      │         │ • Summary of convo  │
    │ • role: "data sci"  │         │ • Current goal      │
    │ • domain: "ML"      │         │ • Progress made     │
    │                     │         │                     │
    │ Scope: USER         │         │ Scope: SESSION      │
    │ Persists: Forever   │         │ Persists: Session   │
    └─────────────────────┘         └─────────────────────┘
              │                               │
              │                               │
              ▼                               ▼
    ┌─────────────────────┐         ┌─────────────────────┐
    │ Available in ALL    │         │ Available in THIS   │
    │ future sessions     │         │ session only        │
    │ with this user      │         │                     │
    └─────────────────────┘         └─────────────────────┘
    
    
    KEY DIFFERENCES:
    
    │ Aspect          │ User Profile          │ Session Context       │
    │─────────────────│───────────────────────│───────────────────────│
    │ Scope           │ All sessions          │ Single session        │
    │ Persists        │ Indefinitely          │ Session lifetime      │
    │ Content         │ Facts about user      │ Conversation state    │
    │ Updates         │ When user info found  │ Every few messages    │
    │ Use case        │ Personalization       │ Continuity            │
    """)


# =============================================================================
# PRACTICAL PATTERNS
# =============================================================================


def demo_personalized_assistance():
    """Show how both stores enable personalized help."""
    print("\n" + "=" * 60)
    print("PATTERN: Personalized Assistance")
    print("=" * 60)

    print("""
    User Profile provides:
    ✓ User's name for personal greeting
    ✓ Expertise level for appropriate explanations
    ✓ Tech stack for relevant examples
    ✓ Role for context-appropriate advice
    
    Session Context provides:
    ✓ What we're working on right now
    ✓ Progress made so far
    ✓ Current blockers or questions
    ✓ Continuity if conversation was interrupted
    
    Combined, the agent can say:
    
    "Alex, based on your Python/ML background and our progress on
     the deployment decision, I'd recommend SageMaker for faster
     iteration. Want me to show you the deployment code?"
    
    Instead of:
    
    "Based on your requirements, here are some deployment options..."
    """)


def demo_context_recovery():
    """Show how session context recovers from message truncation."""
    print("\n" + "=" * 60)
    print("PATTERN: Context Recovery")
    print("=" * 60)

    print("""
    Long conversation scenario:
    
    Message 1-10: Initial discussion (may be truncated)
    Message 11-20: Deep dive on topic
    Message 21+: Current context window
    
    Without session context:
    - Agent loses context from messages 1-10
    - User must repeat information
    - Frustrating experience
    
    With session context:
    - Summary captures key points from ALL messages
    - Goal and progress track the full conversation
    - Agent maintains continuity even after truncation
    
    Session context is especially valuable for:
    - Complex multi-step tasks
    - Long debugging sessions
    - Planning and execution workflows
    """)


# =============================================================================
# CONFIGURATION OPTIONS
# =============================================================================


def show_configuration_options():
    """Different ways to configure the combined setup."""
    print("\n" + "=" * 60)
    print("CONFIGURATION OPTIONS")
    print("=" * 60)

    print("""
    MINIMAL (Just tracking):

        learning=LearningMachine(
            db=db,
            user_profile=True,       # Defaults
            session_context=True,    # Defaults
        )


    ALWAYS EXTRACTION (Automatic):

        learning=LearningMachine(
            db=db,
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,  # Auto-extract
            ),
            session_context=SessionContextConfig(
                enable_planning=False,  # Just summary
            ),
        )


    PLANNING ENABLED:

        learning=LearningMachine(
            db=db,
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            session_context=SessionContextConfig(
                enable_planning=True,  # Track goal/plan/progress
            ),
        )


    AGENTIC USER PROFILE:

        learning=LearningMachine(
            db=db,
            user_profile=UserProfileConfig(
                mode=LearningMode.AGENTIC,  # Agent controls saving
            ),
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
        )


    Note: Session context only supports ALWAYS mode.
    User profile supports both ALWAYS and AGENTIC modes.
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("COMBINED: USER PROFILE + SESSION CONTEXT")
    print("=" * 60)

    # Usage scenarios
    demo_new_user_new_session()
    demo_returning_user_new_session()
    demo_same_session_continuation()

    # Understanding
    show_data_flow()

    # Patterns
    demo_personalized_assistance()
    demo_context_recovery()

    # Configuration
    show_configuration_options()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    Combining user profile and session context gives you:
    
    USER PROFILE (Long-term)
    - Who the user is
    - Their preferences and expertise
    - Persists across all sessions
    
    SESSION CONTEXT (Short-term)
    - What this conversation is about
    - Current goals and progress
    - Survives message truncation
    
    Together they enable:
    ✓ Personalized interactions
    ✓ Conversation continuity
    ✓ No repeated questions
    ✓ Context-aware assistance
    
    This is the recommended baseline for most assistant agents.
    """)
