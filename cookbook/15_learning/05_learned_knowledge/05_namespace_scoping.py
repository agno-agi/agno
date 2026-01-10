"""
Learned Knowledge: Namespace Scoping

Namespaces allow you to organize and isolate learned knowledge for different
contexts: per-user private knowledge, shared team knowledge, project-specific
knowledge, or global organizational knowledge.

Key concepts:
- Namespace determines who can access knowledge
- Same knowledge can exist in multiple namespaces
- Search can span multiple namespaces
- Promotion patterns: user → team → global

Run: python -m cookbook.learned_knowledge.05_namespace_scoping
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode
from agno.learn.config import LearnedKnowledgeConfig
from agno.models.openai import OpenAIChat

# Database URL - use environment variable in production
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# NAMESPACE STRATEGIES
# =============================================================================


def demo_user_namespace():
    """Private knowledge for individual users."""
    print("\n" + "=" * 60)
    print("USER NAMESPACE - Private Knowledge")
    print("=" * 60)

    # Each user has isolated knowledge
    alice_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        learning=LearningMachine(
            db=db,
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace="user:alice",  # Alice's private namespace
            ),
        ),
        user_id="alice",
    )

    bob_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        db=db,
        learning=LearningMachine(
            db=db,
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace="user:bob",  # Bob's private namespace
            ),
        ),
        user_id="bob",
    )

    print("""
    Namespace Pattern: user:{user_id}
    
    Each user builds their own knowledge base:
    - Alice's learnings are private to Alice
    - Bob's learnings are private to Bob
    - No cross-contamination between users
    
    Use cases:
    - Personal assistants
    - Individual preferences and patterns
    - Private work techniques
    """)


def demo_team_namespace():
    """Shared knowledge within a team."""
    print("\n" + "=" * 60)
    print("TEAM NAMESPACE - Shared Team Knowledge")
    print("=" * 60)

    # Team members share a knowledge namespace
    team_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        learning=LearningMachine(
            db=db,
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace="team:engineering",  # Shared team namespace
            ),
        ),
    )

    print("""
    Namespace Pattern: team:{team_name}
    
    All team members contribute to and read from shared knowledge:
    - Coding standards and conventions
    - Common troubleshooting solutions
    - Team-specific workflows
    
    Benefits:
    - Knowledge sharing across team members
    - Collective learning compounds
    - New members get instant access to team wisdom
    """)


def demo_project_namespace():
    """Project-specific knowledge isolation."""
    print("\n" + "=" * 60)
    print("PROJECT NAMESPACE - Project-Specific Knowledge")
    print("=" * 60)

    project_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        learning=LearningMachine(
            db=db,
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace="project:phoenix",  # Project-specific namespace
            ),
        ),
    )

    print("""
    Namespace Pattern: project:{project_name}
    
    Knowledge scoped to a specific project:
    - Architecture decisions
    - Known issues and workarounds
    - Integration patterns
    - Domain-specific insights
    
    Benefits:
    - Clean separation between projects
    - Project context stays relevant
    - Archive when project completes
    """)


def demo_global_namespace():
    """Organization-wide shared knowledge."""
    print("\n" + "=" * 60)
    print("GLOBAL NAMESPACE - Organization Knowledge")
    print("=" * 60)

    global_agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        learning=LearningMachine(
            db=db,
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace="global",  # Organization-wide namespace
            ),
        ),
    )

    print("""
    Namespace Pattern: global
    
    Organization-wide knowledge accessible to all:
    - Company-wide best practices
    - Universal patterns and standards
    - Cross-team learnings
    
    Consider:
    - Higher bar for what gets saved globally
    - May want approval workflow (PROPOSE mode)
    - Regular curation to maintain quality
    """)


# =============================================================================
# HIERARCHICAL NAMESPACE PATTERNS
# =============================================================================


def demo_hierarchical_namespaces():
    """Combining multiple namespace levels."""
    print("\n" + "=" * 60)
    print("HIERARCHICAL NAMESPACES")
    print("=" * 60)

    print("""
    Common hierarchy pattern:
    
    ┌─────────────────────────────────────────────────────────┐
    │                      global                             │
    │  Organization-wide knowledge (highest quality bar)      │
    │                                                         │
    │  ┌─────────────────────────────────────────────────┐   │
    │  │               team:engineering                   │   │
    │  │  Team-specific patterns and conventions          │   │
    │  │                                                  │   │
    │  │  ┌─────────────────────────────────────────┐    │   │
    │  │  │           user:alice                     │    │   │
    │  │  │  Personal preferences and patterns       │    │   │
    │  │  └─────────────────────────────────────────┘    │   │
    │  │                                                  │   │
    │  │  ┌─────────────────────────────────────────┐    │   │
    │  │  │            user:bob                      │    │   │
    │  │  │  Personal preferences and patterns       │    │   │
    │  │  └─────────────────────────────────────────┘    │   │
    │  └─────────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────────┘
    
    Search can cascade: user → team → global
    Promotion path: user → team → global (via curation)
    """)


def demo_multi_namespace_agent():
    """Agent that can access multiple namespaces."""
    print("\n" + "=" * 60)
    print("MULTI-NAMESPACE ACCESS")
    print("=" * 60)

    # Agent with primary namespace but can search others
    # Note: This requires custom tool configuration

    print("""
    Pattern: Primary namespace with fallback search
    
    Configuration approach:
    
    1. Set primary namespace for writing:
       learned_knowledge=LearnedKnowledgeConfig(
           namespace="user:alice",  # Writes go here
       )
    
    2. Custom search tool that queries multiple namespaces:
       - First search user namespace
       - Then search team namespace
       - Finally search global namespace
       - Deduplicate and rank results
    
    3. Promotion workflow:
       - User saves knowledge locally
       - Curator reviews and promotes to team/global
       - Original stays in user namespace
    """)

    # Example of namespace-aware search configuration
    namespaces_to_search = [
        "user:alice",  # User's personal learnings
        "team:engineering",  # Team's shared knowledge
        "global",  # Organization knowledge
    ]

    print(f"\n    Search order: {' → '.join(namespaces_to_search)}")


# =============================================================================
# NAMESPACE NAMING CONVENTIONS
# =============================================================================


def show_naming_conventions():
    """Best practices for namespace naming."""
    print("\n" + "=" * 60)
    print("NAMESPACE NAMING CONVENTIONS")
    print("=" * 60)

    print("""
    Recommended patterns:
    
    USER NAMESPACES
    ---------------
    user:{user_id}              User's private knowledge
    user:{user_id}:work         User's work-specific knowledge
    user:{user_id}:personal     User's personal knowledge
    
    TEAM NAMESPACES
    ---------------
    team:{team_name}            Team's shared knowledge
    team:{team_name}:onboarding New member documentation
    team:{team_name}:runbooks   Operational procedures
    
    PROJECT NAMESPACES
    ------------------
    project:{project_id}        Project-specific knowledge
    project:{project_id}:arch   Architecture decisions
    project:{project_id}:debug  Debugging knowledge
    
    DOMAIN NAMESPACES
    -----------------
    domain:{domain}             Domain-specific knowledge
    domain:security             Security best practices
    domain:performance          Performance patterns
    
    SPECIAL NAMESPACES
    ------------------
    global                      Organization-wide knowledge
    archive:{date}              Archived knowledge
    experimental                Testing/experimental learnings
    
    
    Naming rules:
    ✓ Use lowercase
    ✓ Use colons as separators
    ✓ Be consistent across organization
    ✓ Include type prefix (user, team, project)
    ✗ Avoid spaces or special characters
    ✗ Don't use overly deep hierarchies
    """)


# =============================================================================
# NAMESPACE LIFECYCLE
# =============================================================================


def show_lifecycle_patterns():
    """Managing namespace lifecycle."""
    print("\n" + "=" * 60)
    print("NAMESPACE LIFECYCLE PATTERNS")
    print("=" * 60)

    print("""
    CREATION
    --------
    Namespaces are created implicitly when first written to.
    No explicit creation needed.
    
    MIGRATION
    ---------
    Moving knowledge between namespaces:
    
    1. Export from source namespace
    2. Transform if needed (update metadata, references)
    3. Import to target namespace
    4. Verify in target
    5. Remove from source (optional)
    
    ARCHIVAL
    --------
    When projects complete or teams reorganize:
    
    project:phoenix → archive:2024:project:phoenix
    
    Benefits:
    - Keeps active namespaces clean
    - Preserves historical knowledge
    - Can be restored if needed
    
    CLEANUP
    -------
    Periodic maintenance tasks:
    
    - Remove stale/outdated knowledge
    - Merge duplicate learnings
    - Promote valuable user learnings to team/global
    - Archive completed project namespaces
    
    MONITORING
    ----------
    Track namespace health:
    
    - Knowledge count per namespace
    - Usage/search frequency
    - Last updated timestamps
    - Quality metrics (if available)
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("LEARNED KNOWLEDGE: NAMESPACE SCOPING")
    print("=" * 60)

    # Namespace strategies
    demo_user_namespace()
    demo_team_namespace()
    demo_project_namespace()
    demo_global_namespace()

    # Advanced patterns
    demo_hierarchical_namespaces()
    demo_multi_namespace_agent()

    # Best practices
    show_naming_conventions()
    show_lifecycle_patterns()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    Namespace scoping organizes knowledge for different contexts:
    
    1. USER NAMESPACES (user:{id})
       Private knowledge for individuals
    
    2. TEAM NAMESPACES (team:{name})
       Shared knowledge within teams
    
    3. PROJECT NAMESPACES (project:{name})
       Project-specific knowledge isolation
    
    4. GLOBAL NAMESPACE
       Organization-wide knowledge
    
    Best practices:
    - Use consistent naming conventions
    - Implement promotion workflows
    - Plan for namespace lifecycle
    - Consider multi-namespace search for agents
    """)
