"""
Pattern: Team Knowledge Agent

A knowledge management agent that helps teams capture, organize, and
retrieve institutional knowledge.

Features:
- Captures knowledge from conversations and documents
- Organizes information by topic and relevance
- Answers questions using accumulated knowledge
- Identifies knowledge gaps

Run: python -m cookbook.patterns.team_knowledge_agent
"""

from agno.agent import Agent
from agno.learn import LearningMachine, LearningMode
from agno.learn.config import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    SessionContextConfig,
)
from agno.models.openai import OpenAIChat
from cookbook.db import db_url

# =============================================================================
# TEAM KNOWLEDGE AGENT CONFIGURATION
# =============================================================================


def create_knowledge_agent(
    team: str,
    session_id: str,
) -> Agent:
    """
    Create a team knowledge agent.

    Learning setup:
    - Session context: Current query or knowledge capture session
    - Entity memory: People, projects, concepts, systems
    - Learned knowledge: Insights, decisions, best practices

    Note: No user_profile - this agent serves the team, not individuals
    """
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        description="Team knowledge curator and retrieval assistant",
        instructions=[
            "Capture important knowledge shared in conversations",
            "Organize information for easy retrieval",
            "Answer questions using team knowledge base",
            "Connect related concepts and information",
            "Identify when information may be outdated",
            "Suggest when knowledge gaps should be filled",
        ],
        learning=LearningMachine(
            db_url=db_url,
            # Query session tracking
            session_context=SessionContextConfig(
                enable_planning=False,
            ),
            # Team entities (people, projects, systems)
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,
                namespace=f"team:{team}:entities",
            ),
            # Team knowledge base
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace=f"team:{team}:kb",
            ),
        ),
        session_id=session_id,
        markdown=True,
    )


# =============================================================================
# USAGE EXAMPLES
# =============================================================================


def demo_knowledge_capture():
    """Show how knowledge is captured."""
    print("\n" + "=" * 60)
    print("KNOWLEDGE CAPTURE")
    print("=" * 60)

    print("""
    Team member shares information:
    
    User: "Just so everyone knows, we decided to use PostgreSQL
          instead of MySQL for the new project. Main reasons:
          - Better JSON support for our use case
          - Team already has PostgreSQL experience
          - Needed JSONB for nested query performance"
    
    
    Agent captures:
    
    LEARNED KNOWLEDGE:
    {
      "title": "Database Decision: PostgreSQL for New Project",
      "type": "decision",
      "date": "2024-01-15",
      "decision": "Use PostgreSQL instead of MySQL",
      "rationale": [
        "Better JSON support for document-style data",
        "Team expertise in PostgreSQL",
        "JSONB needed for nested query performance"
      ],
      "context": "New project database selection",
      "tags": ["database", "architecture", "decision"]
    }
    
    ENTITY MEMORY:
    - Entity: "New Project" 
      - Fact: "Uses PostgreSQL database"
      - Event: "Database decision made 2024-01-15"
    
    
    Agent confirms:
    "Got it! I've captured the PostgreSQL decision with the rationale.
     This will be searchable under 'database', 'architecture', or
     'new project'. Should I add any additional context?"
    """)


def demo_knowledge_retrieval():
    """Show how knowledge is retrieved."""
    print("\n" + "=" * 60)
    print("KNOWLEDGE RETRIEVAL")
    print("=" * 60)

    print("""
    New team member asks a question:
    
    User: "Why are we using PostgreSQL?"
    
    
    Agent searches:
    - LEARNED KNOWLEDGE: "PostgreSQL database decision"
    - ENTITY MEMORY: Projects using PostgreSQL
    
    
    Agent responds:
    "The team chose PostgreSQL for the new project (decided Jan 15).
    
     Key reasons:
     • Better JSON support for our document-style data
     • Team already has PostgreSQL experience  
     • JSONB provides better nested query performance
    
     This was chosen over MySQL specifically for the JSON capabilities."
    
    
    More complex query:
    
    User: "What architectural decisions have we made this quarter?"
    
    
    Agent searches:
    - LEARNED KNOWLEDGE with type="decision", date in Q1
    
    
    Agent responds:
    "Q1 architectural decisions:
    
     1. **Database**: PostgreSQL (Jan 15)
        - For JSON support and team expertise
     
     2. **API Framework**: FastAPI (Jan 22)
        - Async support, automatic OpenAPI docs
     
     3. **Deployment**: Kubernetes (Feb 1)
        - Standardize with other services
     
     4. **Caching**: Redis (Feb 10)
        - Session storage and rate limiting
     
     Want details on any of these?"
    """)


def demo_entity_knowledge():
    """Show entity-based knowledge."""
    print("\n" + "=" * 60)
    print("ENTITY-BASED KNOWLEDGE")
    print("=" * 60)

    print("""
    ENTITY MEMORY tracks team resources:
    
    PERSON: Sarah Chen
    ┌─────────────────────────────────────────────────────────────┐
    │ role: Senior Engineer                                       │
    │ expertise: [PostgreSQL, Python, System Design]             │
    │ projects: [New Project, API Redesign]                      │
    │ go_to_for: "Database architecture questions"               │
    └─────────────────────────────────────────────────────────────┘
    
    SYSTEM: Auth Service
    ┌─────────────────────────────────────────────────────────────┐
    │ type: microservice                                          │
    │ owner: Platform Team                                        │
    │ tech_stack: [Python, FastAPI, PostgreSQL]                  │
    │ documentation: /docs/auth-service                          │
    │ known_issues: ["Rate limiting needs tuning"]               │
    │ dependencies: [Redis, User Service]                        │
    └─────────────────────────────────────────────────────────────┘
    
    PROJECT: API Redesign
    ┌─────────────────────────────────────────────────────────────┐
    │ status: In Progress                                         │
    │ team: [Sarah, Mike, Lisa]                                  │
    │ timeline: Q1-Q2 2024                                       │
    │ key_decisions: [FastAPI, OpenAPI 3.1, async-first]        │
    │ blockers: ["Waiting on Auth Service rate limit fix"]       │
    └─────────────────────────────────────────────────────────────┘
    
    
    Queries use this structure:
    
    User: "Who should I talk to about database design?"
    
    Agent: "Sarah Chen is the go-to for database architecture.
           She's the senior engineer with PostgreSQL expertise
           and worked on the New Project database selection."
    
    
    User: "What's blocking the API Redesign?"
    
    Agent: "The API Redesign is waiting on the Auth Service rate
           limit fix (owned by Platform Team). That's the current
           blocker for the project."
    """)


def demo_knowledge_curation():
    """Show knowledge maintenance."""
    print("\n" + "=" * 60)
    print("KNOWLEDGE CURATION")
    print("=" * 60)

    print("""
    The agent helps maintain knowledge quality:
    
    STALENESS DETECTION:
    
    User: "What version of Python are we using?"
    
    Agent: "According to our records (from 6 months ago), we're
           using Python 3.10. However, this information might be
           outdated. Should I flag this for verification?"
    
    
    CONFLICT DETECTION:
    
    User: "We've decided to switch to MySQL for the project"
    
    Agent: "I have a previous decision recorded (Jan 15) that
           the team chose PostgreSQL for this project. Should I:
           
           1. Update to reflect the change to MySQL
           2. Record this as a decision change with context
           3. Check if this is a different project?
           
           What's the context for this change?"
    
    
    GAP IDENTIFICATION:
    
    User: "What's our approach to error handling?"
    
    Agent: "I don't have documented error handling guidelines
           in the knowledge base. This seems like an important
           gap. Would you like to:
           
           1. Document the current approach
           2. Flag this for team discussion
           3. Search for related existing patterns?"
    
    
    PERIODIC REVIEW:
    
    Agent can surface for review:
    - Knowledge items not accessed in 6+ months
    - Decisions that may need revisiting
    - Information marked as temporary
    """)


# =============================================================================
# ADVANCED PATTERNS
# =============================================================================


def show_advanced_patterns():
    """Advanced knowledge management patterns."""
    print("\n" + "=" * 60)
    print("ADVANCED PATTERNS")
    print("=" * 60)

    print("""
    KNOWLEDGE HIERARCHIES:
    
    Organization-wide knowledge:
    └── org:acme:kb
        ├── Company policies
        ├── Cross-team standards
        └── Shared best practices
    
    Team-specific knowledge:
    └── team:engineering:kb
        ├── Technical decisions
        ├── Architecture patterns
        └── Team processes
    
    Project-specific knowledge:
    └── project:phoenix:kb
        ├── Project decisions
        ├── Domain knowledge
        └── Implementation details
    
    
    KNOWLEDGE PROMOTION:
    
    1. Team member shares useful pattern
    2. Agent saves to team:engineering:kb
    3. Pattern proves valuable across teams
    4. Curator promotes to org:acme:kb
    5. All teams benefit
    
    
    KNOWLEDGE TYPES:
    
    Decisions (with rationale):
    - What was decided
    - Why it was decided
    - When and by whom
    - Alternatives considered
    
    How-To (procedures):
    - Step-by-step processes
    - Prerequisites
    - Common issues
    - Examples
    
    Concepts (definitions):
    - What something is
    - How it relates to other concepts
    - Examples and non-examples
    
    Reference (facts):
    - URLs, credentials (non-sensitive)
    - Contact information
    - Specifications
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
    SINGLE TEAM:
    
        entity_memory=EntityMemoryConfig(
            namespace="team:engineering",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace="team:engineering",
        ),
    
    
    MULTI-TEAM WITH HIERARCHY:
    
        # Team-specific agent
        entity_memory=EntityMemoryConfig(
            namespace="team:engineering",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace="team:engineering",
            # Could implement multi-namespace search
        ),
    
    
    PROJECT-SCOPED:
    
        entity_memory=EntityMemoryConfig(
            namespace=f"project:{project_id}",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"project:{project_id}",
        ),
    
    
    READ-HEAVY (Mostly retrieval):
    
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.ALWAYS,  # Auto-extract
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,  # Review before saving
        ),
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PATTERN: TEAM KNOWLEDGE AGENT")
    print("=" * 60)

    demo_knowledge_capture()
    demo_knowledge_retrieval()
    demo_entity_knowledge()
    demo_knowledge_curation()
    show_advanced_patterns()
    show_configuration_options()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    Team Knowledge Agent Setup:
    
    SESSION CONTEXT
    - Current query context
    - Multi-turn knowledge capture sessions
    
    ENTITY MEMORY
    - Team members and expertise
    - Systems and services
    - Projects and status
    - Relationships
    
    LEARNED KNOWLEDGE
    - Decisions with rationale
    - How-to procedures
    - Best practices
    - Concepts and definitions
    
    No USER PROFILE - serves team, not individuals
    
    Benefits:
    ✓ Institutional knowledge preservation
    ✓ Easy knowledge retrieval
    ✓ Expertise discovery
    ✓ Decision traceability
    """)
