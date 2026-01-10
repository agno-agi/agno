"""
Pattern: Sales Agent with Learning

A sales assistant that learns about prospects, deals, and successful
sales patterns to improve conversion rates.

Features:
- Tracks prospect information and interactions
- Learns buying signals and objection patterns
- Builds knowledge of successful approaches
- Maintains deal pipeline context

Run: python -m cookbook.patterns.sales_agent
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
# SALES AGENT CONFIGURATION
# =============================================================================


def create_sales_agent(
    sales_rep_id: str,
    session_id: str,
    org_id: str = "default",
) -> Agent:
    """
    Create a sales agent with learning capabilities.

    Learning setup:
    - User profile: Sales rep's style and expertise
    - Session context: Current sales conversation
    - Entity memory: Prospects, companies, deals (org-shared)
    - Learned knowledge: Sales patterns, objection handling (org-shared)
    """
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        description="Sales assistant focused on understanding needs and providing value",
        instructions=[
            "Focus on understanding the prospect's needs first",
            "Track buying signals and concerns",
            "Reference relevant case studies and social proof",
            "Handle objections with empathy and data",
            "Save successful patterns for team learning",
            "Update prospect status after each interaction",
        ],
        learning=LearningMachine(
            db=db,
            # Sales rep profile
            user_profile=UserProfileConfig(
                mode=LearningMode.ALWAYS,
            ),
            # Current sales conversation
            session_context=SessionContextConfig(
                enable_planning=True,
            ),
            # CRM-like entity tracking (org-shared)
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.AGENTIC,
                namespace=f"org:{org_id}:crm",
            ),
            # Sales playbook knowledge (org-shared)
            learned_knowledge=LearnedKnowledgeConfig(
                mode=LearningMode.AGENTIC,
                namespace=f"org:{org_id}:sales",
            ),
        ),
        user_id=sales_rep_id,
        session_id=session_id,
        markdown=True,
    )


# =============================================================================
# USAGE EXAMPLES
# =============================================================================


def demo_prospect_tracking():
    """Show how prospects are tracked."""
    print("\n" + "=" * 60)
    print("PROSPECT TRACKING")
    print("=" * 60)

    print("""
    ENTITY MEMORY tracks prospects and companies:
    
    COMPANY: TechStartup Inc
    ┌─────────────────────────────────────────────────────────────┐
    │ industry: SaaS                                              │
    │ size: 50-100 employees                                      │
    │ stage: Series A                                             │
    │ tech_stack: [Python, React, AWS]                           │
    │ pain_points:                                                 │
    │   - Manual deployment process                               │
    │   - Scaling challenges                                      │
    │ budget_cycle: Q4                                            │
    │ decision_timeline: 30 days                                  │
    └─────────────────────────────────────────────────────────────┘
    
    PROSPECT: Jennifer Lee
    ┌─────────────────────────────────────────────────────────────┐
    │ company: TechStartup Inc                                    │
    │ role: VP Engineering                                        │
    │ decision_maker: Yes                                         │
    │ communication_style: Data-driven, prefers specifics        │
    │ concerns: [Integration complexity, team bandwidth]          │
    │ buying_signals:                                             │
    │   - Asked about pricing (2024-01-10)                       │
    │   - Requested technical demo (2024-01-12)                  │
    │ objections_raised:                                          │
    │   - "Concerned about learning curve"                       │
    └─────────────────────────────────────────────────────────────┘
    
    DEAL: TechStartup-Enterprise
    ┌─────────────────────────────────────────────────────────────┐
    │ company: TechStartup Inc                                    │
    │ stage: Demo Scheduled                                       │
    │ value: $50,000 ARR                                         │
    │ probability: 40%                                            │
    │ next_action: Technical demo on Jan 15                       │
    │ stakeholders: [Jennifer Lee, CTO (name unknown)]           │
    │ competition: [Competitor A mentioned]                       │
    └─────────────────────────────────────────────────────────────┘
    
    
    This enables context-rich conversations:
    
    Sales Rep: "Prep me for the TechStartup demo"
    
    Agent: "For your TechStartup demo with Jennifer:
           
           Key points:
           • She's data-driven - lead with metrics
           • Main concern: Learning curve - show easy onboarding
           • They use Python/React/AWS - customize examples
           • Competitor A in play - highlight our integration speed
           
           Her buying signals are strong (asked pricing, requested demo).
           Focus on addressing the learning curve objection."
    """)


def demo_sales_knowledge():
    """Show how sales patterns are captured."""
    print("\n" + "=" * 60)
    print("SALES KNOWLEDGE BUILDING")
    print("=" * 60)

    print("""
    LEARNED KNOWLEDGE captures successful patterns:
    
    OBJECTION HANDLING:
    {
      "objection": "Concerned about learning curve",
      "effective_responses": [
        "Show 2-hour onboarding video completion rates (95%)",
        "Reference similar-sized company onboarding (TechCorp: 
         full team productive in 1 week)",
        "Offer dedicated onboarding specialist"
      ],
      "success_rate": "75% proceed after this handling",
      "context": "Most effective with technical decision makers"
    }
    
    WINNING PATTERN:
    {
      "title": "Technical Demo to Close",
      "pattern": [
        "Lead with their specific pain point",
        "Show 3 features max (relevance over volume)",
        "Include live coding/config example",
        "End with ROI calculator",
        "Send follow-up within 2 hours"
      ],
      "avg_conversion": "45% to next stage",
      "learned_from": "Analysis of 20 successful demos"
    }
    
    INDUSTRY INSIGHT:
    {
      "industry": "SaaS Series A",
      "key_drivers": ["Speed to market", "Developer experience"],
      "typical_concerns": ["Integration time", "Support quality"],
      "budget_timing": "Q4 budget planning, Q1 execution",
      "decision_process": "Typically CTO + VP Eng"
    }
    
    
    During calls, agent surfaces relevant knowledge:
    
    Prospect: "I'm worried my team won't have time to learn this"
    
    Agent (to rep): "Learning curve objection - consider:
                    • 2-hour onboarding, 95% completion rate
                    • TechCorp (similar size) was productive in 1 week
                    • Offer dedicated onboarding specialist
                    
                    This response has 75% success rate."
    """)


def demo_deal_progression():
    """Show how deals progress through pipeline."""
    print("\n" + "=" * 60)
    print("DEAL PROGRESSION")
    print("=" * 60)

    print("""
    Session tracking maintains deal context:
    
    SESSION 1 (Discovery call):
    ┌─────────────────────────────────────────────────────────────┐
    │ Goal: Qualify TechStartup opportunity                       │
    │ Progress:                                                   │
    │   ✓ Identified pain points (manual deployment)             │
    │   ✓ Budget confirmed ($40-60k range)                       │
    │   ✓ Decision timeline (30 days)                            │
    │   ✓ Demo scheduled for Jan 15                              │
    │ Next: Technical demo preparation                            │
    └─────────────────────────────────────────────────────────────┘
    
    ENTITY UPDATE after session:
    - Deal stage: Discovery → Demo Scheduled
    - Probability: 20% → 40%
    - New info added to prospect/company entities
    
    
    SESSION 2 (Demo prep):
    ┌─────────────────────────────────────────────────────────────┐
    │ Goal: Prepare for TechStartup demo                          │
    │ Plan:                                                       │
    │   1. Review prospect profile and concerns                   │
    │   2. Customize demo for Python/AWS stack                    │
    │   3. Prepare learning curve objection handling              │
    │   4. Create ROI calculator with their numbers               │
    │ Progress: Demo slides customized, ROI ready                 │
    └─────────────────────────────────────────────────────────────┘
    
    
    SESSION 3 (Post-demo):
    ┌─────────────────────────────────────────────────────────────┐
    │ Goal: Process demo feedback, plan follow-up                 │
    │ Outcome:                                                    │
    │   ✓ Demo well received                                     │
    │   ✓ CTO wants pilot program details                        │
    │   ✓ Learning curve concern addressed                       │
    │   - Price discussion deferred to next call                 │
    │ Next: Pilot proposal by Jan 18                              │
    └─────────────────────────────────────────────────────────────┘
    
    ENTITY UPDATE:
    - Deal stage: Demo Scheduled → Pilot Proposed
    - Probability: 40% → 60%
    - New stakeholder: CTO (John, identified during demo)
    """)


# =============================================================================
# TEAM BENEFITS
# =============================================================================


def show_team_benefits():
    """Show how team learning compounds."""
    print("\n" + "=" * 60)
    print("TEAM LEARNING BENEFITS")
    print("=" * 60)

    print("""
    Shared namespace enables team learning:
    
    SCENARIO: New sales rep joins team
    
    Before LearningMachine:
    - Shadows calls for weeks
    - Learns objection handling through trial and error
    - Doesn't know what worked for similar prospects
    
    With LearningMachine:
    - Instant access to winning patterns
    - Objection handling playbook with success rates
    - Similar prospect/deal history
    - Industry-specific insights
    
    
    CROSS-POLLINATION:
    
    Rep A closes deal with SaaS startup:
    → Saves: "ROI calculator most effective closer for Series A"
    
    Rep B picks up new SaaS startup lead:
    → Searches: "SaaS startup closing techniques"
    → Finds: Rep A's insight + others
    → Applies: Uses ROI calculator early
    
    
    KNOWLEDGE COMPOUNDING:
    
    Month 1: 5 saved patterns
    Month 3: 25 saved patterns + refinements
    Month 6: 50+ patterns, success rates tracked
    Month 12: Comprehensive playbook, continuously improving
    
    New reps benefit from entire team's experience immediately.
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
    SMALL SALES TEAM:
    
        entity_memory=EntityMemoryConfig(
            namespace="sales:crm",  # All reps share CRM
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace="sales:playbook",  # All reps share playbook
        ),
    
    
    TERRITORY-BASED:
    
        entity_memory=EntityMemoryConfig(
            namespace=f"sales:{territory}:crm",  # Territory CRM
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace="sales:playbook",  # Global playbook
        ),
    
    
    PRODUCT-SPECIFIC:
    
        entity_memory=EntityMemoryConfig(
            namespace=f"sales:{product}:crm",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"sales:{product}:playbook",
        ),
    
    
    ENTERPRISE (Multi-tenant):
    
        entity_memory=EntityMemoryConfig(
            namespace=f"org:{org_id}:sales:crm",
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            namespace=f"org:{org_id}:sales:playbook",
        ),
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("PATTERN: SALES AGENT")
    print("=" * 60)

    demo_prospect_tracking()
    demo_sales_knowledge()
    demo_deal_progression()
    show_team_benefits()
    show_configuration_options()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
    Sales Agent Learning Setup:
    
    USER PROFILE
    - Sales rep's style and strengths
    - Product expertise areas
    
    SESSION CONTEXT
    - Current call/meeting context
    - Deal discussion progress
    - Action items
    
    ENTITY MEMORY (CRM-like)
    - Companies and prospects
    - Deal pipeline
    - Interaction history
    - Relationships and stakeholders
    
    LEARNED KNOWLEDGE (Playbook)
    - Objection handling patterns
    - Winning demo techniques
    - Industry insights
    - Competitive intelligence
    
    Benefits:
    ✓ Context-rich conversations
    ✓ Team knowledge sharing
    ✓ Pattern recognition
    ✓ New rep onboarding
    """)
