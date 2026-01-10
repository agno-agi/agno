"""
Pattern: Coding Assistant with Learning

A coding assistant that learns about the codebase, developer preferences,
and effective patterns to provide increasingly relevant help.

Features:
- Learns developer's coding style and preferences
- Tracks debugging sessions and solutions
- Builds knowledge of codebase structure
- Remembers successful patterns and fixes

Run: python -m cookbook.patterns.coding_assistant
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode
from agno.learn.config import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# CODING ASSISTANT CONFIGURATION
# =============================================================================


def create_coding_assistant(
    developer_id: str,
    session_id: str,
    project: str = "default",
) -> Agent:
    """
    Create a coding assistant with learning capabilities.

    Learning setup:
    - User profile: Developer's languages, style, expertise
    - Session context: Current task/debugging session
    - Entity memory: Codebase components, dependencies, patterns
    - Learned knowledge: Bug patterns, solutions, best practices
    """
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        description="Expert coding assistant",
        instructions=[
            "Understand the full context before suggesting code",
            "Match the developer's coding style and conventions",
            "Explain your reasoning, not just the solution",
            "Consider edge cases and error handling",
            "Reference relevant parts of the codebase",
            "Save successful bug fixes and patterns for reuse",
        ],
        learning=LearningMachine(
            db=db,
            # Developer profile
            user_profile=UserProfileConfig(
                mode=LearningMode.BACKGROUND,
            ),
            # Task/debug session tracking
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            # Codebase knowledge (project-specific)
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.BACKGROUND,
                namespace=f"project:{project}",
            ),
            # Coding patterns and solutions (shared)
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace=f"project:{project}:kb",
            ),
        ),
        user_id=developer_id,
        session_id=session_id,
        markdown=True,
    )


# =============================================================================
# USAGE EXAMPLE
# =============================================================================


def demo_debugging_session():
    """Demonstrate a debugging session."""
    print("\n" + "=" * 60)
    print("DEBUGGING SESSION DEMO")
    print("=" * 60)

    print("""
    Scenario: Developer debugging a race condition
    
    TURN 1:
    Developer: "I'm getting intermittent failures in our payment
               service. Sometimes transactions complete twice.
               Here's the code: [paste]"
    
    Agent processes:
    
    1. SESSION CONTEXT captures:
       - Goal: "Fix duplicate transaction bug in payment service"
       - Progress: "Investigating race condition"
    
    2. USER PROFILE may learn:
       - Working on: Payment service
       - Language: (detected from code)
    
    3. ENTITY MEMORY records:
       - Component: Payment service
       - Issue: Duplicate transactions
       - Pattern: Possible race condition
    
    4. LEARNED KNOWLEDGE searched:
       - Query: "duplicate transaction race condition payment"
       - May find: "Similar issue caused by missing idempotency keys"
    
    
    Agent responds:
    "This looks like a classic race condition in payment processing.
     The issue is in your transaction handler:
     
     ```python
     # Current code - race condition possible
     if not transaction_exists(id):
         process_transaction(id)  # Gap here!
         save_transaction(id)
     ```
     
     Two requests can both pass the check before either saves.
     
     Solution: Use idempotency keys with database constraints:
     
     ```python
     # Fixed - atomic operation
     try:
         save_transaction_with_unique_constraint(id)
         process_transaction(id)
     except DuplicateKeyError:
         return existing_transaction(id)
     ```
     
     I've seen this pattern work well in similar payment systems."
    """)


def demo_style_learning():
    """Show how the assistant learns coding style."""
    print("\n" + "=" * 60)
    print("CODING STYLE LEARNING")
    print("=" * 60)

    print("""
    Over time, USER PROFILE learns:
    
    ┌─────────────────────────────────────────────────────────────┐
    │ Developer Profile: dev_sarah                                │
    │                                                             │
    │ Languages: Python (primary), TypeScript                     │
    │ Frameworks: FastAPI, React                                  │
    │                                                             │
    │ Style preferences (observed):                               │
    │   • Uses type hints extensively                             │
    │   • Prefers f-strings over .format()                       │
    │   • Writes docstrings in Google style                       │
    │   • Uses black formatting                                   │
    │   • Prefers explicit over implicit                          │
    │                                                             │
    │ Testing approach:                                           │
    │   • Uses pytest                                             │
    │   • Prefers fixtures over setup methods                     │
    │   • Writes integration tests                                │
    └─────────────────────────────────────────────────────────────┘
    
    
    When generating code, assistant matches style:
    
    Developer: "Add error handling to this function"
    
    Agent generates (matching observed style):
    
    ```python
    def process_payment(
        amount: Decimal,
        customer_id: str,
    ) -> PaymentResult:
        \"\"\"Process a payment for a customer.
        
        Args:
            amount: Payment amount in dollars.
            customer_id: Unique customer identifier.
            
        Returns:
            PaymentResult with transaction details.
            
        Raises:
            PaymentError: If payment processing fails.
        \"\"\"
        if amount <= 0:
            raise PaymentError(f"Invalid amount: {amount}")
        ...
    ```
    
    Note: Type hints, Google docstring, f-string - all match Sarah's style!
    """)


def demo_codebase_knowledge():
    """Show how entity memory builds codebase understanding."""
    print("\n" + "=" * 60)
    print("CODEBASE KNOWLEDGE")
    print("=" * 60)

    print("""
    ENTITY MEMORY accumulates codebase knowledge:
    
    COMPONENT: PaymentService
    ┌─────────────────────────────────────────────────────────────┐
    │ type: service                                               │
    │ location: src/services/payment.py                           │
    │ responsibilities:                                           │
    │   - Process transactions                                    │
    │   - Handle refunds                                          │
    │   - Validate payment methods                                │
    │ dependencies: [Database, StripeClient, AuditLogger]        │
    │ known_issues:                                               │
    │   - Race condition (fixed 2024-01)                         │
    │   - Timeout handling needs work                             │
    └─────────────────────────────────────────────────────────────┘
    
    COMPONENT: Database
    ┌─────────────────────────────────────────────────────────────┐
    │ type: infrastructure                                        │
    │ tech: PostgreSQL with SQLAlchemy                           │
    │ patterns_used: Repository pattern                           │
    │ connection_pooling: Yes (max 20)                           │
    │ used_by: [PaymentService, UserService, OrderService]       │
    └─────────────────────────────────────────────────────────────┘
    
    PATTERN: IdempotencyKey
    ┌─────────────────────────────────────────────────────────────┐
    │ type: pattern                                               │
    │ used_in: [PaymentService, OrderService]                    │
    │ implementation: UUID in request header                      │
    │ storage: Redis with 24h TTL                                │
    └─────────────────────────────────────────────────────────────┘
    
    
    Later questions benefit:
    
    Developer: "I need to add refund functionality"
    
    Agent knows:
    - PaymentService handles refunds (existing interface)
    - Uses Repository pattern (follow convention)
    - Idempotency keys needed (project pattern)
    - Connects to StripeClient (integration point)
    """)


def demo_knowledge_accumulation():
    """Show how coding knowledge accumulates."""
    print("\n" + "=" * 60)
    print("KNOWLEDGE ACCUMULATION")
    print("=" * 60)

    print("""
    LEARNED KNOWLEDGE grows with each solved problem:
    
    BUG PATTERN:
    {
      "title": "Payment Race Condition Fix",
      "problem": "Duplicate transactions when concurrent requests",
      "root_cause": "Check-then-act without atomicity",
      "solution": "Idempotency keys with DB unique constraint",
      "code_example": "...",
      "related_services": ["PaymentService", "OrderService"]
    }
    
    BEST PRACTICE:
    {
      "title": "Database Connection Handling",
      "context": "FastAPI with SQLAlchemy async",
      "recommendation": "Use dependency injection with lifespan",
      "code_pattern": "...",
      "learned_from": "Session leak debugging, 2024-01"
    }
    
    PERFORMANCE TIP:
    {
      "title": "Batch Payment Processing",
      "problem": "Slow bulk refunds",
      "solution": "Use asyncio.gather with chunking",
      "improvement": "10x speedup for 1000+ refunds",
      "caveat": "Respect rate limits on payment provider"
    }
    
    
    New problems check existing knowledge:
    
    Developer: "Bulk operations are slow"
    
    Agent: "Based on our previous work on batch refunds, I'd
           suggest the chunked asyncio.gather pattern we used.
           That gave us a 10x speedup. Want me to adapt it?"
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
    SOLO DEVELOPER (Private everything):
    
        entity_memory=EntityMemoryConfig(
            namespace=f"user:{dev_id}:project",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"user:{dev_id}",
        ),
    
    
    TEAM PROJECT (Shared codebase knowledge):
    
        entity_memory=EntityMemoryConfig(
            namespace=f"project:{project_id}",  # Team-shared
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"project:{project_id}",  # Team-shared
        ),
    
    
    MULTI-REPO ORGANIZATION:
    
        entity_memory=EntityMemoryConfig(
            namespace=f"org:{org_id}:repo:{repo_id}",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"org:{org_id}",  # Org-wide patterns
        ),
    
    
    LANGUAGE-SPECIFIC KNOWLEDGE:
    
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"lang:python",  # Python community patterns
        ),
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PATTERN: CODING ASSISTANT")
    print("=" * 60)

    demo_debugging_session()
    demo_style_learning()
    demo_codebase_knowledge()
    demo_knowledge_accumulation()
    show_configuration_options()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    Coding Assistant Learning Setup:
    
    USER PROFILE
    - Languages and frameworks
    - Coding style preferences
    - Testing approach
    - Experience level
    
    SESSION CONTEXT
    - Current task or bug
    - Investigation progress
    - Attempted solutions
    
    ENTITY MEMORY
    - Codebase components
    - Dependencies and relationships
    - Known issues
    - Design patterns used
    
    LEARNED KNOWLEDGE
    - Bug patterns and fixes
    - Best practices
    - Performance tips
    - Code review learnings
    
    Benefits:
    ✓ Style-matched code generation
    ✓ Codebase-aware suggestions
    ✓ Accumulated bug patterns
    ✓ Team knowledge sharing
    """)
