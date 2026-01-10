"""
Combined Learning: User Profile + Entity Memory

Combine user-specific knowledge with entity tracking for rich contextual
understanding. The user profile captures WHO the user is, while entity
memory tracks the things they interact with and care about.

Key concepts:
- User profile: Facts about the user themselves
- Entity memory: Facts about external entities (people, places, things)
- Namespacing: User entities vs global entities
- Cross-references: Linking users to entities

Run: python -m cookbook.combined.02_user_plus_entities
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode
from agno.learn.config import EntityMemoryConfig, UserProfileConfig
from agno.models.openai import OpenAIChat

# Database URL - use environment variable in production
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# BASIC COMBINED SETUP
# =============================================================================


def create_combined_agent(user_id: str) -> Agent:
    """Create agent with user profile and entity memory."""
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        learning=LearningMachine(
            db=db,
            # About the user
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            # About things in the user's world
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.ALWAYS,
                namespace=f"user:{user_id}",  # User's private entity graph
            ),
        ),
        user_id=user_id,
        markdown=True,
    )


def demo_user_vs_entity_distinction():
    """Clarify what goes where."""
    print("\n" + "=" * 60)
    print("USER PROFILE vs ENTITY MEMORY")
    print("=" * 60)

    print("""
    When a user says: "I'm Sarah, a PM at Acme Corp. I work with 
    John on the Phoenix project. John is our tech lead."
    
    
    USER PROFILE captures (about Sarah):
    ┌─────────────────────────────────────┐
    │ name: Sarah                         │
    │ role: Product Manager               │
    │ company: Acme Corp                  │
    │ memories:                           │
    │   - "Works on Phoenix project"      │
    │   - "Collaborates with John"        │
    └─────────────────────────────────────┘
    
    ENTITY MEMORY captures (about the world):
    
    Entity: John
    ┌─────────────────────────────────────┐
    │ type: person                        │
    │ facts:                              │
    │   - "Tech lead at Acme Corp"        │
    │   - "Works on Phoenix project"      │
    │ relationships:                      │
    │   - works_with: Sarah               │
    │   - leads: Phoenix project          │
    └─────────────────────────────────────┘
    
    Entity: Phoenix project
    ┌─────────────────────────────────────┐
    │ type: project                       │
    │ facts:                              │
    │   - "Project at Acme Corp"          │
    │ relationships:                      │
    │   - has_team_member: Sarah          │
    │   - has_tech_lead: John             │
    └─────────────────────────────────────┘
    
    
    RULE OF THUMB:
    - User Profile: First-person facts ("I am...", "I work at...")
    - Entity Memory: Third-person facts ("John is...", "The project has...")
    """)


# =============================================================================
# NAMESPACE STRATEGIES
# =============================================================================


def demo_private_entities():
    """User-specific entity namespace."""
    print("\n" + "=" * 60)
    print("PATTERN: Private Entity Namespace")
    print("=" * 60)

    _agent = create_combined_agent(user_id="sarah_123")

    print("""
    Configuration:
        entity_memory=EntityMemoryConfig(
            namespace="user:sarah_123",  # Private to Sarah
        )
    
    Sarah's entity graph is completely private:
    - Her colleagues
    - Her projects  
    - Her clients
    - Her personal contacts
    
    No other user can see or search Sarah's entities.
    
    Use case: Personal assistant, private CRM, individual workspace
    """)


def demo_shared_entities():
    """Shared entity namespace with private user profiles."""
    print("\n" + "=" * 60)
    print("PATTERN: Shared Entities, Private Profiles")
    print("=" * 60)

    def create_team_agent(user_id: str) -> Agent:
        return Agent(
            model=OpenAIChat(id="gpt-4o"),
            db=db,
            learning=LearningMachine(
                db=db,
                # Private user profile
                user_profile=UserProfileConfig(
                    mode=LearningMode.ALWAYS,
                ),
                # Shared entity memory
                entity_memory=EntityMemoryConfig(
                    mode=LearningMode.ALWAYS,
                    namespace="team:engineering",  # Shared namespace
                ),
            ),
            user_id=user_id,
        )

    print("""
    Configuration:
        user_profile: per-user (automatic)
        entity_memory: namespace="team:engineering" (shared)
    
    Benefits:
    - Each user has their own profile (private preferences)
    - All team members share entity knowledge
    - When Sarah adds info about a client, Bob can see it
    - No duplicate entity entries across team
    
    Use case: Team CRM, shared knowledge base, collaborative workspace
    """)


def demo_hybrid_namespace():
    """Both private and shared entity access."""
    print("\n" + "=" * 60)
    print("PATTERN: Hybrid Namespace")
    print("=" * 60)

    print("""
    Some scenarios need both private AND shared entities:
    
    ┌─────────────────────────────────────────────────────┐
    │                 SHARED (team:sales)                  │
    │                                                      │
    │  Clients, Deals, Company info                        │
    │  All team members contribute and access              │
    │                                                      │
    │  ┌────────────────┐  ┌────────────────┐             │
    │  │ user:sarah     │  │ user:bob       │             │
    │  │                │  │                │             │
    │  │ Personal       │  │ Personal       │             │
    │  │ contacts,      │  │ contacts,      │             │
    │  │ private notes  │  │ private notes  │             │
    │  └────────────────┘  └────────────────┘             │
    └─────────────────────────────────────────────────────┘
    
    Implementation approach:
    1. Primary agent uses shared namespace
    2. Separate "personal notes" agent uses user namespace
    OR
    1. Custom tools that route to appropriate namespace
    """)


# =============================================================================
# PRACTICAL EXAMPLES
# =============================================================================


def demo_relationship_tracking():
    """Track relationships between user and entities."""
    print("\n" + "=" * 60)
    print("EXAMPLE: Relationship Tracking")
    print("=" * 60)

    print("""
    User says: "I'm meeting with Dr. Chen tomorrow about the clinical trial.
    She's the principal investigator."
    
    USER PROFILE records:
    - Memory: "Has meeting with Dr. Chen about clinical trial"
    
    ENTITY MEMORY records:
    
    Entity: Dr. Chen
    ┌─────────────────────────────────────┐
    │ type: person                        │
    │ facts:                              │
    │   - "Principal investigator"        │
    │ relationships:                      │
    │   - leads: Clinical Trial           │
    │   - meeting_scheduled: User         │
    └─────────────────────────────────────┘
    
    Entity: Clinical Trial
    ┌─────────────────────────────────────┐
    │ type: project                       │
    │ facts:                              │
    │   - (details from conversation)     │
    │ relationships:                      │
    │   - principal_investigator: Dr. Chen│
    └─────────────────────────────────────┘
    
    Later, when user asks "What do I know about Dr. Chen?",
    agent can retrieve both the relationship graph AND
    user-specific context (the scheduled meeting).
    """)


def demo_entity_evolution():
    """How entities evolve over conversations."""
    print("\n" + "=" * 60)
    print("EXAMPLE: Entity Evolution")
    print("=" * 60)

    print("""
    Conversation 1:
    User: "I'm working with a new vendor called TechSupply."
    
    Entity Created:
    ┌─────────────────────────────────────┐
    │ name: TechSupply                    │
    │ type: company                       │
    │ facts:                              │
    │   - "Vendor"                        │
    │   - "New relationship"              │
    └─────────────────────────────────────┘
    
    
    Conversation 5:
    User: "TechSupply's contact is Mike, he's been really responsive."
    
    Entity Updated + New Entity:
    ┌─────────────────────────────────────┐
    │ name: TechSupply                    │
    │ type: company                       │
    │ facts:                              │
    │   - "Vendor"                        │
    │   - "New relationship"              │
    │   - "Responsive service"            │
    │ relationships:                      │
    │   - has_contact: Mike               │
    └─────────────────────────────────────┘
    
    ┌─────────────────────────────────────┐
    │ name: Mike                          │
    │ type: person                        │
    │ facts:                              │
    │   - "Contact at TechSupply"         │
    │   - "Responsive"                    │
    │ relationships:                      │
    │   - works_at: TechSupply            │
    └─────────────────────────────────────┘
    
    
    Conversation 10:
    User: "We signed a 2-year contract with TechSupply for $50k."
    
    Event Added:
    ┌─────────────────────────────────────┐
    │ entity: TechSupply                  │
    │ event: "Signed 2-year contract"     │
    │ details: "$50k value"               │
    │ date: 2024-01-15                    │
    └─────────────────────────────────────┘
    
    User profile might also capture:
    - Memory: "Managing TechSupply vendor relationship"
    """)


# =============================================================================
# QUERY PATTERNS
# =============================================================================


def show_query_patterns():
    """How to query across both stores."""
    print("\n" + "=" * 60)
    print("QUERY PATTERNS")
    print("=" * 60)

    print("""
    USER-CENTRIC QUERIES
    (Start with user profile, enrich with entities)
    
    Q: "What am I working on?"
    1. Check user profile for current projects
    2. Look up those projects in entity memory for details
    
    Q: "Remind me about my meeting tomorrow"
    1. Check user profile for scheduled meetings
    2. Look up meeting participants in entity memory
    
    
    ENTITY-CENTRIC QUERIES
    (Start with entity memory, relate back to user)
    
    Q: "Tell me about Acme Corp"
    1. Search entity memory for Acme Corp
    2. Include user's relationship (from profile)
    
    Q: "What do I know about Project Phoenix?"
    1. Get entity facts about Phoenix
    2. Get user's involvement from profile
    
    
    RELATIONSHIP QUERIES
    (Traverse the graph)
    
    Q: "Who works on Project Phoenix?"
    1. Get Phoenix entity
    2. Follow relationship edges to team members
    
    Q: "What projects is John involved in?"
    1. Get John entity
    2. Follow project relationship edges
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
    PERSONAL ASSISTANT (Private everything):

        learning=LearningMachine(
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.ALWAYS,
                namespace=f"user:{user_id}",  # Private
            ),
        )


    TEAM WORKSPACE (Shared entities):

        learning=LearningMachine(
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,  # Explicit control
                namespace="team:engineering",  # Shared
            ),
        )


    CRM AGENT (Agentic entity management):

        learning=LearningMachine(
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,  # Agent decides what to track
                namespace="crm:accounts",
            ),
        )


    RESEARCH ASSISTANT (Rich entity extraction):

        learning=LearningMachine(
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.ALWAYS,  # Auto-extract everything
                namespace=f"user:{user_id}:research",
            ),
        )
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("COMBINED: USER PROFILE + ENTITY MEMORY")
    print("=" * 60)

    # Core concepts
    demo_user_vs_entity_distinction()

    # Namespace strategies
    demo_private_entities()
    demo_shared_entities()
    demo_hybrid_namespace()

    # Practical examples
    demo_relationship_tracking()
    demo_entity_evolution()

    # Query patterns
    show_query_patterns()

    # Configuration
    show_configuration_options()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    Combining user profile and entity memory gives you:
    
    USER PROFILE
    - Facts about the user themselves
    - Preferences, role, expertise
    - First-person knowledge
    
    ENTITY MEMORY
    - Facts about external entities
    - People, places, projects, companies
    - Third-person knowledge + relationships
    
    Together they answer:
    - "What do I know about X?" (entity facts + user relationship)
    - "Who is involved in Y?" (entity relationships)
    - "What is the user working on?" (profile + entity details)
    
    Namespace strategies:
    - Private: Personal assistant, individual workspace
    - Shared: Team CRM, collaborative knowledge
    - Hybrid: Both private and shared access
    """)
