"""
Combined Learning: Full Learning Machine

The complete setup using all four learning stores together. This gives
your agent comprehensive learning capabilities across all dimensions.

Key concepts:
- User Profile: Who is this user?
- Session Context: What's this conversation about?
- Entity Memory: What entities are involved?
- Learned Knowledge: What patterns have we discovered?

Run: python -m cookbook.combined.03_full_learning_machine
"""

from agno.agent import Agent
from agno.learn import LearningMachine, LearningMode
from agno.learn.config import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from cookbook.db import db_url

# =============================================================================
# FULL LEARNING MACHINE SETUP
# =============================================================================


def create_full_learning_agent(
    user_id: str, session_id: str, team: str = "default"
) -> Agent:
    """Create agent with all four learning stores."""
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        learning=LearningMachine(
            db_url=db_url,
            # STORE 1: User Profile
            # Learns about the individual user
            user_profile=UserProfileConfig(
                mode=LearningMode.BACKGROUND,  # Auto-extract user info
            ),
            # STORE 2: Session Context
            # Tracks conversation state
            session_context=SessionContextConfig(
                enable_planning=True,  # Track goals and progress
            ),
            # STORE 3: Entity Memory
            # Tracks entities in user's world
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.BACKGROUND,  # Auto-extract entities
                namespace=f"user:{user_id}",  # Private to user
            ),
            # STORE 4: Learned Knowledge
            # Captures reusable insights
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,  # Agent decides what to save
                namespace=f"team:{team}",  # Shared with team
            ),
        ),
        user_id=user_id,
        session_id=session_id,
        markdown=True,
    )


# =============================================================================
# UNDERSTANDING THE FOUR STORES
# =============================================================================


def show_four_stores_overview():
    """Explain what each store does."""
    print("\n" + "=" * 60)
    print("THE FOUR LEARNING STORES")
    print("=" * 60)

    print("""
    ┌────────────────────────────────────────────────────────────────┐
    │                     LEARNING MACHINE                            │
    ├────────────────────────────────────────────────────────────────┤
    │                                                                 │
    │  ┌─────────────────┐         ┌─────────────────┐              │
    │  │  USER PROFILE   │         │ SESSION CONTEXT │              │
    │  │                 │         │                 │              │
    │  │ "Who is this    │         │ "What is this   │              │
    │  │  user?"         │         │  conversation   │              │
    │  │                 │         │  about?"        │              │
    │  │ • Name          │         │                 │              │
    │  │ • Role          │         │ • Summary       │              │
    │  │ • Preferences   │         │ • Goal          │              │
    │  │ • Expertise     │         │ • Progress      │              │
    │  │                 │         │                 │              │
    │  │ Scope: USER     │         │ Scope: SESSION  │              │
    │  └─────────────────┘         └─────────────────┘              │
    │                                                                 │
    │  ┌─────────────────┐         ┌─────────────────┐              │
    │  │ ENTITY MEMORY   │         │LEARNED KNOWLEDGE│              │
    │  │                 │         │                 │              │
    │  │ "What entities  │         │ "What patterns  │              │
    │  │  are involved?" │         │  have we found?"│              │
    │  │                 │         │                 │              │
    │  │ • People        │         │ • Best practices│              │
    │  │ • Projects      │         │ • Solutions     │              │
    │  │ • Companies     │         │ • Insights      │              │
    │  │ • Relationships │         │ • Patterns      │              │
    │  │                 │         │                 │              │
    │  │ Scope: NAMESPACE│         │ Scope: NAMESPACE│              │
    │  └─────────────────┘         └─────────────────┘              │
    │                                                                 │
    └────────────────────────────────────────────────────────────────┘
    """)


def show_data_flow():
    """Show how data flows through the stores."""
    print("\n" + "=" * 60)
    print("DATA FLOW IN A CONVERSATION")
    print("=" * 60)

    print("""
    User Message: "I'm Alex, a PM at TechCorp. I'm trying to fix a bug
    in the auth service that John reported. We tried restarting but that
    didn't work. Any ideas?"
    
    
    ┌─────────────────────────────────────────────────────────────────┐
    │                      EXTRACTION PHASE                            │
    └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │ USER PROFILE extracts:                                          │
    │   • name: Alex                                                   │
    │   • role: PM at TechCorp                                        │
    └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │ SESSION CONTEXT updates:                                        │
    │   • summary: "Debugging auth service bug reported by John"      │
    │   • goal: "Fix auth service bug"                                │
    │   • progress: "Tried restart, didn't work"                      │
    └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │ ENTITY MEMORY extracts:                                         │
    │                                                                  │
    │   Entity: John                                                   │
    │   • type: person                                                │
    │   • fact: "Reported auth service bug"                           │
    │                                                                  │
    │   Entity: Auth Service                                          │
    │   • type: service                                               │
    │   • fact: "Has a bug"                                           │
    │   • event: "Restart attempted, unsuccessful"                    │
    └─────────────────────────────────────────────────────────────────┘
    
    
    ┌─────────────────────────────────────────────────────────────────┐
    │                      RESPONSE PHASE                              │
    └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │ LEARNED KNOWLEDGE searched:                                     │
    │   Query: "auth service bug troubleshooting"                     │
    │   Found: "Auth service bugs often caused by expired tokens.     │
    │           Check /var/log/auth/tokens.log"                       │
    └─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │ Agent Response:                                                  │
    │   "Alex, since restarting didn't help, let's check the token   │
    │    logs. Based on past issues, auth bugs are often caused by    │
    │    expired tokens. Can you run: cat /var/log/auth/tokens.log"   │
    └─────────────────────────────────────────────────────────────────┘
    
    
    If solution works, agent might save to LEARNED KNOWLEDGE:
    "Auth service bug with John resolved by clearing expired tokens"
    """)


# =============================================================================
# WHEN TO USE ALL FOUR STORES
# =============================================================================


def show_when_to_use_all_four():
    """Guide on when full setup is appropriate."""
    print("\n" + "=" * 60)
    print("WHEN TO USE ALL FOUR STORES")
    print("=" * 60)

    print("""
    USE ALL FOUR WHEN:
    
    ✓ Long-term user relationships (need user profile)
    ✓ Complex multi-turn conversations (need session context)
    ✓ Many entities to track (need entity memory)
    ✓ Patterns worth capturing for reuse (need learned knowledge)
    
    EXAMPLES:
    
    1. SUPPORT AGENT
       - User: Customer's history and preferences
       - Session: Current issue being resolved
       - Entities: Products, services, past tickets
       - Knowledge: Troubleshooting patterns, solutions
    
    2. PROJECT MANAGER
       - User: PM's communication style, reports
       - Session: Current planning/review session
       - Entities: Team members, tasks, milestones
       - Knowledge: Estimation patterns, risk factors
    
    3. RESEARCH ASSISTANT
       - User: Researcher's interests, expertise
       - Session: Current research question
       - Entities: Papers, authors, concepts
       - Knowledge: Research patterns, methodologies
    
    4. CODING ASSISTANT
       - User: Developer's tech stack, style
       - Session: Current debugging/feature session
       - Entities: Codebase components, dependencies
       - Knowledge: Bug patterns, best practices
    
    
    SIMPLER ALTERNATIVES:
    
    If you don't need all four, use fewer:
    
    │ Use Case              │ Recommended Stores                    │
    │───────────────────────│───────────────────────────────────────│
    │ Simple chatbot        │ session_context only                  │
    │ Personal assistant    │ user_profile + session_context        │
    │ Knowledge base        │ learned_knowledge only                │
    │ CRM agent             │ user_profile + entity_memory          │
    │ Full-featured agent   │ All four stores                       │
    """)


# =============================================================================
# STORE INTERACTIONS
# =============================================================================


def show_store_interactions():
    """How stores complement each other."""
    print("\n" + "=" * 60)
    print("STORE INTERACTIONS")
    print("=" * 60)

    print("""
    The stores work together, not in isolation:
    
    
    USER PROFILE ←→ ENTITY MEMORY
    ──────────────────────────────
    User profile knows WHO the user is.
    Entity memory knows what entities they interact with.
    
    Example: "Alex manages Project Phoenix"
    - User profile: Alex is a PM
    - Entity memory: Phoenix project exists, Alex manages it
    
    Together: "As the PM for Phoenix, you might want to..."
    
    
    SESSION CONTEXT ←→ LEARNED KNOWLEDGE
    ─────────────────────────────────────
    Session tracks current conversation state.
    Learned knowledge provides relevant past insights.
    
    Example: Debugging session
    - Session: "Currently debugging auth timeout issue"
    - Knowledge: "Auth timeouts often caused by connection pool exhaustion"
    
    Together: "Based on your current issue and past patterns..."
    
    
    ENTITY MEMORY ←→ LEARNED KNOWLEDGE
    ───────────────────────────────────
    Entities provide context for knowledge retrieval.
    Knowledge provides insights about entities.
    
    Example: "How should I approach this client?"
    - Entity: Client info, past interactions
    - Knowledge: Patterns that worked with similar clients
    
    Together: "For clients like Acme (enterprise, technical), 
               focus on ROI metrics as that's worked before"
    
    
    ALL FOUR TOGETHER
    ─────────────────
    User: "Help me prepare for my meeting with John about the API"
    
    1. User profile: User is Alex, prefers bullet-point summaries
    2. Session context: Current goal is meeting prep
    3. Entity memory: John is tech lead, API project details
    4. Learned knowledge: Past successful meeting prep patterns
    
    Response: "Alex, here's a bullet-point prep for your John meeting:
               - API status: 80% complete [from entity memory]
               - John prefers technical details [from entity memory]
               - Include demo, worked well last time [from knowledge]"
    """)


# =============================================================================
# CONFIGURATION PATTERNS
# =============================================================================


def show_configuration_patterns():
    """Different ways to configure all four stores."""
    print("\n" + "=" * 60)
    print("CONFIGURATION PATTERNS")
    print("=" * 60)

    print("""
    PATTERN 1: Background Everything (Maximum auto-learning)
    
        learning=LearningMachine(
            user_profile=UserProfileConfig(mode=LearningMode.BACKGROUND),
            session_context=SessionContextConfig(enable_planning=True),
            entity_memory=EntityMemoryConfig(mode=LearningMode.BACKGROUND),
            learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.BACKGROUND),
        )
    
    Pros: Learns everything automatically
    Cons: May learn noise, less control
    
    
    PATTERN 2: Selective Agentic (Controlled learning)
    
        learning=LearningMachine(
            user_profile=UserProfileConfig(mode=LearningMode.BACKGROUND),
            session_context=SessionContextConfig(enable_planning=True),
            entity_memory=EntityMemoryConfig(mode=LearningMode.AGENTIC),
            learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
        )
    
    Pros: Background for user/session, explicit for entities/knowledge
    Cons: Requires agent to decide what to save
    
    
    PATTERN 3: Propose Mode for Knowledge (With review)
    
        learning=LearningMachine(
            user_profile=UserProfileConfig(mode=LearningMode.BACKGROUND),
            session_context=SessionContextConfig(enable_planning=True),
            entity_memory=EntityMemoryConfig(mode=LearningMode.BACKGROUND),
            learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.PROPOSE),
        )
    
    Pros: Entities auto-learned, knowledge reviewed before saving
    Cons: Requires approval workflow
    
    
    PATTERN 4: Namespace Isolation (Multi-tenant)
    
        learning=LearningMachine(
            user_profile=UserProfileConfig(mode=LearningMode.BACKGROUND),
            session_context=SessionContextConfig(enable_planning=True),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.BACKGROUND,
                namespace=f"org:{org_id}:user:{user_id}",
            ),
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace=f"org:{org_id}",
            ),
        )
    
    Pros: Strict tenant isolation
    Cons: More complex namespace management
    """)


# =============================================================================
# COST CONSIDERATIONS
# =============================================================================


def show_cost_considerations():
    """Understanding the cost of full learning."""
    print("\n" + "=" * 60)
    print("COST CONSIDERATIONS")
    print("=" * 60)

    print("""
    Running all four stores has costs:
    
    TOKEN COSTS (per message, approximate):
    ┌─────────────────────────────────────────────────────────────┐
    │ Store              │ Background Mode │ Agentic Mode        │
    │────────────────────│─────────────────│─────────────────────│
    │ User Profile       │ ~500-1000 tokens│ Tool calls vary     │
    │ Session Context    │ ~300-500 tokens │ N/A                 │
    │ Entity Memory      │ ~500-1500 tokens│ Tool calls vary     │
    │ Learned Knowledge  │ ~300-800 tokens │ Tool calls vary     │
    │────────────────────│─────────────────│─────────────────────│
    │ TOTAL              │ ~1600-3800/msg  │ Depends on usage    │
    └─────────────────────────────────────────────────────────────┘
    
    DATABASE COSTS:
    - PgVector storage for embeddings
    - Query costs for retrieval
    - Relatively low compared to token costs
    
    LATENCY:
    - Background extraction adds ~1-3 seconds post-response
    - Retrieval adds ~100-500ms per store queried
    - Total added latency: ~0.5-2 seconds
    
    
    OPTIMIZATION STRATEGIES:
    
    1. Start minimal, add stores as needed
    2. Use AGENTIC mode to reduce unnecessary extractions
    3. Batch background processing when possible
    4. Cache frequently accessed data
    5. Use appropriate namespace granularity
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("FULL LEARNING MACHINE: ALL FOUR STORES")
    print("=" * 60)

    # Overview
    show_four_stores_overview()
    show_data_flow()

    # Guidance
    show_when_to_use_all_four()
    show_store_interactions()

    # Configuration
    show_configuration_patterns()
    show_cost_considerations()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    The full Learning Machine combines all four stores:
    
    1. USER PROFILE
       Who: Individual user facts and preferences
       When: All sessions with this user
    
    2. SESSION CONTEXT  
       What: Current conversation state
       When: This session only
    
    3. ENTITY MEMORY
       Who/What: External entities and relationships
       When: Based on namespace scope
    
    4. LEARNED KNOWLEDGE
       What: Reusable patterns and insights
       When: Based on namespace scope
    
    Use all four when you need:
    ✓ Long-term user relationships
    ✓ Complex conversation tracking
    ✓ Rich entity context
    ✓ Accumulated knowledge
    
    Start simple, add stores as your needs grow.
    """)
