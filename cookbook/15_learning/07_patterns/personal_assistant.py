"""
Pattern: Personal Assistant with Learning

A personal assistant that learns about the user over time to provide
increasingly personalized and proactive help.

Features:
- Remembers user preferences and routines
- Tracks ongoing tasks and projects
- Knows user's contacts and relationships
- Learns what works best for this user

Run: python -m cookbook.patterns.personal_assistant
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode
from agno.learn.config import (
    EntityMemoryConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# PERSONAL ASSISTANT CONFIGURATION
# =============================================================================


def create_personal_assistant(
    user_id: str,
    session_id: str,
) -> Agent:
    """
    Create a personal assistant with learning capabilities.

    Learning setup:
    - User profile: Preferences, routines, communication style
    - Session context: Current conversation and task
    - Entity memory: Contacts, projects, places, events
    """
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        description="Personal assistant",
        instructions=[
            "Be helpful, friendly, and proactive",
            "Remember user preferences without being asked",
            "Anticipate needs based on patterns",
            "Keep track of important people and events",
            "Respect privacy and be discreet",
        ],
        learning=LearningMachine(
            db=db,
            # User preferences and patterns
            user_profile=UserProfileConfig(
                mode=LearningMode.BACKGROUND,
            ),
            # Current conversation
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            # People, places, events, projects
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.BACKGROUND,
                namespace=f"user:{user_id}:personal",
            ),
        ),
        user_id=user_id,
        session_id=session_id,
        markdown=True,
    )


# =============================================================================
# USAGE EXAMPLES
# =============================================================================


def demo_preference_learning():
    """Show how preferences are learned."""
    print("\n" + "=" * 60)
    print("PREFERENCE LEARNING")
    print("=" * 60)

    print("""
    Over time, the assistant learns:
    
    USER PROFILE
    ┌─────────────────────────────────────────────────────────────┐
    │ Name: Alex Chen                                             │
    │ Location: San Francisco                                     │
    │ Timezone: Pacific                                           │
    │                                                             │
    │ Communication:                                              │
    │   • Prefers concise responses                              │
    │   • Likes bullet points for lists                          │
    │   • Responds well to direct suggestions                    │
    │                                                             │
    │ Schedule patterns:                                          │
    │   • Usually free mornings before 10am                      │
    │   • Gym on Tuesday/Thursday evenings                       │
    │   • Prefers no meetings on Fridays                         │
    │                                                             │
    │ Preferences:                                                │
    │   • Coffee: Oat milk latte                                 │
    │   • Food: Vegetarian, likes Thai                           │
    │   • Travel: Window seat, early flights                     │
    └─────────────────────────────────────────────────────────────┘
    
    
    These preferences apply automatically:
    
    User: "Book me a flight to NYC"
    
    Assistant: "I'll look for early morning flights with window
               seats. What dates work for you?"
               
    (No need to ask about preferences - already known!)
    """)


def demo_entity_tracking():
    """Show how the assistant tracks people and things."""
    print("\n" + "=" * 60)
    print("ENTITY TRACKING")
    print("=" * 60)

    print("""
    ENTITY MEMORY tracks important entities:
    
    PERSON: Sarah (sister)
    ┌─────────────────────────────────────────────────────────────┐
    │ relationship: Sister                                        │
    │ birthday: March 15                                          │
    │ location: Boston                                            │
    │ interests: Hiking, photography                              │
    │ recent: Planning visit in April                             │
    └─────────────────────────────────────────────────────────────┘
    
    PERSON: Dr. Martinez
    ┌─────────────────────────────────────────────────────────────┐
    │ relationship: Doctor                                        │
    │ specialty: Primary care                                     │
    │ clinic: SF Medical Group                                    │
    │ last_visit: 2024-01-15 (annual checkup)                    │
    └─────────────────────────────────────────────────────────────┘
    
    PROJECT: Kitchen Renovation
    ┌─────────────────────────────────────────────────────────────┐
    │ status: Planning                                            │
    │ budget: $30,000                                             │
    │ timeline: Start in June                                     │
    │ contacts: [Jim's Contracting, Design Studio A]             │
    │ decisions_needed: [Countertop material, Cabinet style]     │
    └─────────────────────────────────────────────────────────────┘
    
    EVENT: Sarah's Visit
    ┌─────────────────────────────────────────────────────────────┐
    │ dates: April 10-15                                          │
    │ purpose: Sister visiting from Boston                        │
    │ plans: [Hiking at Muir Woods, dinner reservations needed]  │
    └─────────────────────────────────────────────────────────────┘
    
    
    Queries use this context:
    
    User: "What's happening with my home project?"
    
    Assistant: "Your kitchen renovation is in planning:
               • Budget: $30k
               • Starting in June
               • You still need to decide on countertops and cabinets
               • Jim's Contracting is the lead"
    """)


def demo_proactive_assistance():
    """Show proactive help based on learned patterns."""
    print("\n" + "=" * 60)
    print("PROACTIVE ASSISTANCE")
    print("=" * 60)

    print("""
    The assistant can be proactive based on knowledge:
    
    USER PROFILE knows:
    - Sister's birthday is March 15
    - User usually sends gifts 2 weeks ahead
    - Sister likes photography
    
    On March 1st:
    
    Assistant: "Quick reminder - Sarah's birthday is in 2 weeks.
               Given her interest in photography, would you like
               some gift ideas? I could also help order something."
    
    
    SESSION CONTEXT tracks ongoing tasks:
    
    User mentioned: "I need to call the contractor this week"
    
    On Friday (if not done):
    
    Assistant: "Did you get a chance to call Jim's Contracting
               about the kitchen renovation? Want me to draft
               a message instead?"
    
    
    ENTITY MEMORY enables context-aware help:
    
    User: "I need a restaurant for Tuesday"
    
    Assistant knows Tuesday = gym day, prefers vegetarian:
    
    "For Tuesday evening, how about Thai Basil near your gym?
     It's vegetarian-friendly and you could stop by after
     your workout. They have quick service too."
    """)


def demo_context_continuity():
    """Show how context persists across sessions."""
    print("\n" + "=" * 60)
    print("CONTEXT CONTINUITY")
    print("=" * 60)

    print("""
    Session 1 (Monday):
    User: "I'm planning Sarah's visit next month"
    Assistant: "Great! What dates is she coming?"
    User: "April 10-15. We want to do some hiking."
    Assistant: "I'll note that. Muir Woods would be perfect 
               given the season..."
    
    
    Session 2 (Wednesday):
    User: "Can you remind me what we discussed about my sister?"
    
    FROM SESSION (if same session):
    - Recent conversation context
    
    FROM ENTITY MEMORY (always available):
    - Sarah entity with visit details
    - Event: April 10-15 visit
    - Plans: Hiking at Muir Woods
    
    Assistant: "For Sarah's April 10-15 visit, we discussed:
               • Hiking at Muir Woods
               • You still need dinner reservations
               • She's coming from Boston
               
               Want me to look into restaurant options?"
    
    
    Session 3 (Following week):
    User: "What do I need to prepare for April?"
    
    FROM ENTITY MEMORY:
    - Sarah's visit: April 10-15
    - Kitchen renovation: Starting June
    - Any other April events
    
    Assistant: "For April:
               • Sarah's visit (April 10-15) - hiking planned,
                 dinner reservations still needed
               • Tax deadline April 15
               • No kitchen prep yet (that's June)
               
               Should we focus on the visit prep?"
    """)


# =============================================================================
# CONFIGURATION OPTIONS
# =============================================================================


def show_configuration_options():
    """Different configuration approaches."""
    print("\n" + "=" * 60)
    print("CONFIGURATION OPTIONS")
    print("=" * 60)

    print("""
    BASIC PERSONAL ASSISTANT:
    
        learning=LearningMachine(
            user_profile=True,
            session_context=True,
        )
    
    
    WITH ENTITY TRACKING:
    
        learning=LearningMachine(
            user_profile=UserProfileConfig(
                mode=LearningMode.BACKGROUND,
            ),
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            entity_memory=EntityMemoryConfig(
                namespace=f"user:{user_id}:personal",
            ),
        )
    
    
    FAMILY SHARED ASSISTANT:
    
        learning=LearningMachine(
            user_profile=UserProfileConfig(
                mode=LearningMode.BACKGROUND,
            ),
            entity_memory=EntityMemoryConfig(
                namespace=f"family:{family_id}",  # Shared
            ),
        )
    
    
    Note: Personal assistants typically don't need
    learned_knowledge since insights are user-specific
    and captured in user_profile/entity_memory.
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PATTERN: PERSONAL ASSISTANT")
    print("=" * 60)

    demo_preference_learning()
    demo_entity_tracking()
    demo_proactive_assistance()
    demo_context_continuity()
    show_configuration_options()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    Personal Assistant Learning Setup:
    
    USER PROFILE
    - Name, location, timezone
    - Communication preferences
    - Schedule patterns
    - Likes/dislikes
    
    SESSION CONTEXT
    - Current conversation
    - Active tasks
    - Recent requests
    
    ENTITY MEMORY
    - People (family, friends, contacts)
    - Places (home, work, favorites)
    - Projects and tasks
    - Events and dates
    
    Benefits:
    ✓ Personalized without asking
    ✓ Proactive reminders
    ✓ Context across sessions
    ✓ Relationship awareness
    """)
