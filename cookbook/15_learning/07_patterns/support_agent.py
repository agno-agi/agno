"""
Pattern: Support Agent with Learning

A customer support agent that learns from interactions to provide
better, faster support over time.

Features:
- Remembers customer history and preferences
- Tracks ongoing support sessions
- Builds knowledge base of solutions
- Learns from successful resolutions

Run: python -m cookbook.patterns.support_agent
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

# Database URL - use environment variable in production
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# SUPPORT AGENT CONFIGURATION
# =============================================================================


def create_support_agent(
    customer_id: str,
    ticket_id: str,
    org_id: str = "default_org",
) -> Agent:
    """
    Create a support agent with full learning capabilities.

    Learning setup:
    - User profile: Customer's history, preferences, expertise level
    - Session context: Current ticket/issue being resolved
    - Entity memory: Products, past tickets, known issues (shared)
    - Learned knowledge: Solutions, troubleshooting patterns (shared)
    """
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        # Support agent personality
        description="Helpful customer support agent",
        instructions=[
            "Be empathetic and patient with customers",
            "Start by understanding the customer's issue fully",
            "Check if this issue has been solved before",
            "Provide clear, step-by-step solutions",
            "Confirm the issue is resolved before closing",
            "Save successful solutions for future reference",
        ],
        learning=LearningMachine(
            db=db,
            # Customer profile (per-customer)
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            # Ticket tracking (per-session)
            session_context=SessionContextConfig(
                enable_planning=True,  # Track resolution progress
            ),
            # Product/ticket knowledge (org-wide)
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.ALWAYS,
                namespace=f"org:{org_id}:support",
            ),
            # Solution knowledge base (org-wide)
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,  # Agent saves solutions
                namespace=f"org:{org_id}:kb",
            ),
        ),
        user_id=customer_id,
        session_id=ticket_id,
        markdown=True,
    )


# =============================================================================
# USAGE EXAMPLE
# =============================================================================


def demo_support_interaction():
    """Demonstrate a support interaction."""
    print("\n" + "=" * 60)
    print("SUPPORT AGENT DEMO")
    print("=" * 60)

    # Create agent for this customer and ticket
    agent = create_support_agent(
        customer_id="cust_12345",
        ticket_id="ticket_98765",
        org_id="acme_corp",
    )

    print("""
    Scenario: Customer contacts support about login issues
    
    TURN 1:
    Customer: "Hi, I can't log into my account. It keeps saying 
              'invalid credentials' even though I know my password
              is correct. I'm using the Chrome browser."
    
    Agent processes:
    
    1. SESSION CONTEXT captures:
       - Goal: "Resolve login issue - invalid credentials error"
       - Progress: "Customer reported Chrome browser, correct password"
    
    2. USER PROFILE learns (if new customer):
       - Browser preference: Chrome
       - Technical level: (assessed from language)
    
    3. ENTITY MEMORY updates:
       - Login system: "Invalid credentials error reported"
    
    4. LEARNED KNOWLEDGE searched:
       - Query: "login invalid credentials Chrome"
       - May find: "Invalid credentials often caused by cached cookies"
    
    
    Agent responds:
    "I'm sorry you're having trouble logging in! This 'invalid 
     credentials' error with Chrome is often caused by cached data.
     
     Let's try clearing your browser cache:
     1. Click the three dots menu in Chrome
     2. Go to Settings > Privacy > Clear browsing data
     3. Select 'Cookies' and 'Cached images'
     4. Click 'Clear data'
     5. Try logging in again
     
     Let me know if that works!"
    """)


def demo_knowledge_building():
    """Show how the agent builds knowledge."""
    print("\n" + "=" * 60)
    print("KNOWLEDGE BUILDING")
    print("=" * 60)

    print("""
    After successful resolution:
    
    Customer: "That worked! Thanks so much!"
    
    Agent actions:
    
    1. SESSION CONTEXT updated:
       - Progress: "Issue resolved - cache clearing fixed login"
    
    2. LEARNED KNOWLEDGE saved:
       {
         "title": "Login invalid credentials fix",
         "problem": "User gets 'invalid credentials' error despite 
                    correct password, Chrome browser",
         "solution": "Clear browser cache and cookies",
         "success_rate": "Confirmed working",
         "tags": ["login", "Chrome", "cache", "credentials"]
       }
    
    3. ENTITY MEMORY updated:
       - Customer entity: "Had login issue, resolved via cache clear"
    
    
    Next time similar issue occurs:
    
    New Customer: "Can't log in, wrong password error in Chrome"
    
    Agent immediately finds previous solution:
    "I've seen this before! Let's clear your Chrome cache..."
    
    Resolution time: Minutes instead of extended troubleshooting
    """)


def demo_returning_customer():
    """Show how agent remembers customers."""
    print("\n" + "=" * 60)
    print("RETURNING CUSTOMER")
    print("=" * 60)

    print("""
    Same customer returns with new issue:
    
    Customer: "Hey, now I'm having trouble with the dashboard loading"
    
    Agent has context:
    
    FROM USER PROFILE:
    - Previous ticket about login issues
    - Uses Chrome browser
    - Technical level: intermediate
    
    FROM ENTITY MEMORY:
    - Customer's past interactions
    - Dashboard component information
    
    
    Agent responds:
    "Hi again! Sorry to hear the dashboard is giving you trouble.
     
     Since you're using Chrome, let's first check if it's another
     cache issue (that fixed your login last time). 
     
     Can you try a hard refresh with Ctrl+Shift+R?
     
     If that doesn't work, we'll dig deeper."
    
    
    Benefits:
    ✓ Personalized greeting (remembers customer)
    ✓ Relevant first suggestion (based on history)
    ✓ Appropriate technical level
    ✓ No need to re-ask basic questions
    """)


# =============================================================================
# ADVANCED PATTERNS
# =============================================================================


def show_escalation_pattern():
    """Pattern for escalating complex issues."""
    print("\n" + "=" * 60)
    print("ESCALATION PATTERN")
    print("=" * 60)

    print("""
    When issue exceeds agent capability:
    
    1. SESSION CONTEXT tracks failed attempts:
       - Progress: "Tried cache clear, hard refresh, incognito - all failed"
    
    2. Agent recognizes escalation needed:
       "I've tried our standard troubleshooting steps but the issue
        persists. Let me escalate this to our technical team.
        
        I'll include all the steps we've tried so you don't have
        to repeat them."
    
    3. ENTITY MEMORY captures escalation:
       - Ticket event: "Escalated to L2 support"
       - Issue entity: "Unresolved by standard troubleshooting"
    
    4. Handoff includes full context:
       - Customer profile
       - Session summary
       - Steps attempted
       - Error details
    
    
    L2 agent picks up with full context - no customer repetition.
    """)


def show_proactive_pattern():
    """Pattern for proactive support."""
    print("\n" + "=" * 60)
    print("PROACTIVE SUPPORT PATTERN")
    print("=" * 60)

    print("""
    Using learned knowledge proactively:
    
    Scenario: Known issue affecting Chrome users this week
    
    LEARNED KNOWLEDGE contains:
    {
      "title": "Chrome 120 compatibility issue",
      "affected": "Dashboard charts not rendering",
      "workaround": "Use Firefox temporarily",
      "permanent_fix": "Pending in v2.5.1 release",
      "status": "active"
    }
    
    
    When customer mentions Chrome + dashboard:
    
    Agent immediately:
    "I see you're using Chrome and having dashboard issues.
     
     We have a known compatibility issue with Chrome 120 that
     affects chart rendering. Our team is working on a fix
     for the next release.
     
     In the meantime, Firefox works perfectly as a workaround.
     Would you like help switching?"
    
    
    Benefits:
    ✓ Immediate recognition of known issue
    ✓ No unnecessary troubleshooting
    ✓ Sets accurate expectations
    ✓ Provides workaround
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
    SMALL TEAM (Shared everything):
    
        entity_memory=EntityMemoryConfig(
            namespace="support",  # All agents share
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace="support",  # All agents share
        ),
    
    
    MULTI-PRODUCT (Product isolation):
    
        entity_memory=EntityMemoryConfig(
            namespace=f"product:{product_id}:support",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"product:{product_id}:kb",
        ),
    
    
    ENTERPRISE (Tenant isolation):
    
        entity_memory=EntityMemoryConfig(
            namespace=f"org:{org_id}:support",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"org:{org_id}:kb",
        ),
    
    
    TIERED KNOWLEDGE (L1 vs L2 vs L3):
    
        # L1 agents get basic KB
        learned_knowledge=LearnedKnowledgeConfig(
            namespace="kb:l1",
        ),
        
        # L2 agents get advanced KB
        learned_knowledge=LearnedKnowledgeConfig(
            namespace="kb:l2",  # Includes l1 + advanced
        ),
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PATTERN: SUPPORT AGENT")
    print("=" * 60)

    demo_support_interaction()
    demo_knowledge_building()
    demo_returning_customer()

    show_escalation_pattern()
    show_proactive_pattern()
    show_configuration_options()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    Support Agent Learning Setup:
    
    USER PROFILE
    - Customer history and preferences
    - Technical expertise level
    - Past issues and resolutions
    
    SESSION CONTEXT
    - Current ticket tracking
    - Resolution progress
    - Steps attempted
    
    ENTITY MEMORY
    - Products and features
    - Known issues
    - Customer interactions
    
    LEARNED KNOWLEDGE
    - Successful solutions
    - Troubleshooting patterns
    - Workarounds for known issues
    
    Benefits:
    ✓ Faster resolution times
    ✓ Consistent support quality
    ✓ No repeated questions
    ✓ Organizational learning
    """)
