"""
Onboarding Agent Pattern
========================

An agent that guides new users through product setup while learning
their needs, preferences, and goals to provide personalized experiences.

Key Concepts:
- Progressive profiling through natural conversation
- Checkpoint-based progress tracking
- Adaptive flow based on user responses
- Handoff preparation for other agents

Run: python -m cookbook.patterns.onboarding_agent
"""

from agno.learn import LearningMachine, LearningMode

# =============================================================================
# AGENT SETUP
# =============================================================================


def create_onboarding_agent(user_id: str):
    """Create an onboarding agent with progressive profiling."""

    return LearningMachine(
        # Learn user facts for personalization
        user_profile=True,
        # Track onboarding progress
        session_context=True,
        # No entities during onboarding (keep simple)
        entity_memory=False,
        # Capture setup patterns for product improvement
        learned_knowledge={"namespace": "onboarding:patterns"},
        user_id=user_id,
        session_id=f"onboarding-{user_id}",
    )


# =============================================================================
# ONBOARDING FLOW
# =============================================================================

ONBOARDING_STAGES = [
    "welcome",
    "role_discovery",
    "goal_setting",
    "preference_capture",
    "feature_tour",
    "completion",
]

STAGE_QUESTIONS = {
    "welcome": [
        "What brings you to our product today?",
        "Have you used similar tools before?",
    ],
    "role_discovery": [
        "What's your role or primary use case?",
        "Will you be working alone or with a team?",
    ],
    "goal_setting": [
        "What's the first thing you'd like to accomplish?",
        "What does success look like for you?",
    ],
    "preference_capture": [
        "How do you prefer to receive notifications?",
        "Would you like detailed explanations or quick answers?",
    ],
    "feature_tour": [
        "Would you like a guided tour of key features?",
        "Any specific feature you're most curious about?",
    ],
}


def demo_onboarding_flow():
    """Demonstrate progressive onboarding."""

    print("=" * 60)
    print("ONBOARDING FLOW DEMO")
    print("=" * 60)

    machine = create_onboarding_agent("new_user_001")

    # Simulated onboarding conversation
    onboarding_conversation = [
        # Welcome stage
        {
            "role": "assistant",
            "content": "Welcome! I'm here to help you get started. What brings you to our product today?",
        },
        {
            "role": "user",
            "content": "I'm a product manager looking to better organize my team's research and user feedback.",
        },
        {
            "role": "assistant",
            "content": "Great! Product research organization is one of our strengths. Have you used similar tools before?",
        },
        {
            "role": "user",
            "content": "I've used Notion and Airtable but they don't quite fit our workflow.",
        },
        # Role discovery
        {
            "role": "assistant",
            "content": "I understand - those are good tools but can be generic. What's your team size?",
        },
        {
            "role": "user",
            "content": "We have 5 PMs and about 20 engineers who need access to research.",
        },
        {
            "role": "assistant",
            "content": "Perfect size for our team features. Will you be the main admin?",
        },
        {"role": "user", "content": "Yes, I'll set things up and then invite others."},
        # Goal setting
        {
            "role": "assistant",
            "content": "What's the first thing you'd like to accomplish today?",
        },
        {
            "role": "user",
            "content": "I want to import our existing user interview notes and tag them properly.",
        },
        {
            "role": "assistant",
            "content": "We can definitely help with that. What does 'properly tagged' mean for your team?",
        },
        {
            "role": "user",
            "content": "Tags by product area, user segment, and sentiment.",
        },
        # Preference capture
        {
            "role": "assistant",
            "content": "That's a solid taxonomy. Quick question - do you prefer detailed step-by-step guidance or quick tips you can explore?",
        },
        {
            "role": "user",
            "content": "Quick tips usually - I like to figure things out but want help available.",
        },
    ]

    # Process through learning machine
    print("\nProcessing onboarding conversation...")

    result = machine.invoke({"messages": onboarding_conversation})

    # Display extracted profile
    print("\n📋 USER PROFILE CAPTURED:")
    print("-" * 40)

    expected_profile = {
        "role": "Product Manager",
        "team_size": "5 PMs + 20 engineers",
        "use_case": "Research and feedback organization",
        "previous_tools": ["Notion", "Airtable"],
        "admin_status": "Primary admin",
        "first_goal": "Import and tag user interviews",
        "taxonomy": "product area, user segment, sentiment",
        "learning_style": "Quick tips, self-directed",
    }

    for key, value in expected_profile.items():
        print(f"  {key}: {value}")

    # Display session progress
    print("\n📊 ONBOARDING PROGRESS:")
    print("-" * 40)

    progress = {
        "current_stage": "feature_tour",
        "completed_stages": [
            "welcome",
            "role_discovery",
            "goal_setting",
            "preference_capture",
        ],
        "completion_percentage": 80,
        "next_action": "Show import feature tour",
    }

    for key, value in progress.items():
        print(f"  {key}: {value}")


# =============================================================================
# ADAPTIVE FLOW
# =============================================================================


def demo_adaptive_branching():
    """Show how onboarding adapts to user responses."""

    print("\n" + "=" * 60)
    print("ADAPTIVE FLOW DEMO")
    print("=" * 60)

    print("""
    Onboarding Flow Branches Based on User Profile:
    
    ┌─────────────────────────────────────────────────────────┐
    │                      WELCOME                            │
    │              "What brings you here?"                    │
    └────────────────────────┬────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         ┌────────┐    ┌─────────┐    ┌────────┐
         │ Solo   │    │  Team   │    │Enterprise│
         │ User   │    │  Lead   │    │  Admin   │
         └───┬────┘    └────┬────┘    └────┬────┘
             │              │              │
             ▼              ▼              ▼
        Quick Setup    Team Setup     SSO/Security
        Personal       Invite Flow    Compliance
        Workspace      Permissions    Integrations
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                   ┌────────────────┐
                   │  GOAL SETTING  │
                   │  (Personalized)│
                   └────────────────┘
    """)

    # Example branch detection
    print("\n🔀 BRANCH DETECTION:")
    print("-" * 40)

    branch_signals = {
        "solo_user": [
            "mentions 'just me' or 'personal'",
            "no team size mentioned",
            "individual use case",
        ],
        "team_lead": [
            "mentions team size",
            "asks about collaboration",
            "wants to invite others",
        ],
        "enterprise": [
            "mentions SSO or security",
            "large team (50+)",
            "asks about compliance",
        ],
    }

    for branch, signals in branch_signals.items():
        print(f"\n  {branch.upper()}:")
        for signal in signals:
            print(f"    • {signal}")


# =============================================================================
# CHECKPOINT SYSTEM
# =============================================================================


def demo_checkpoint_recovery():
    """Show checkpoint-based progress recovery."""

    print("\n" + "=" * 60)
    print("CHECKPOINT RECOVERY DEMO")
    print("=" * 60)

    print("""
    Checkpoints allow users to resume onboarding:
    
    Session Context Tracks:
    ┌─────────────────────────────────────────────────────────┐
    │ checkpoint: "role_discovery"                            │
    │ completed_steps: ["welcome", "intro_video"]             │
    │ skipped_steps: ["pricing_overview"]                     │
    │ partial_data: {                                         │
    │   "name": "Sarah",                                      │
    │   "email": "sarah@company.com"                          │
    │ }                                                       │
    │ last_question: "What's your team size?"                 │
    │ timestamp: "2024-01-15T10:30:00Z"                       │
    └─────────────────────────────────────────────────────────┘
    """)

    # Simulate recovery
    print("\n🔄 RECOVERY SCENARIO:")
    print("-" * 40)

    recovery_conversation = [
        {
            "role": "assistant",
            "content": "Welcome back, Sarah! Last time we were discussing your team setup. You mentioned you're a PM - how many people will be using this with you?",
        },
        {"role": "user", "content": "Oh right! We have 8 people total."},
    ]

    print("\n  User returns after 2 days...")
    print("  Agent recovers context from session:")
    print("    • Remembers user's name (Sarah)")
    print("    • Knows they're a PM")
    print("    • Resumes at team size question")
    print("    • Skips already-completed steps")


# =============================================================================
# HANDOFF PREPARATION
# =============================================================================


def demo_handoff_preparation():
    """Show preparation for handoff to main agent."""

    print("\n" + "=" * 60)
    print("HANDOFF PREPARATION DEMO")
    print("=" * 60)

    print("""
    When onboarding completes, prepare handoff package:
    
    ┌─────────────────────────────────────────────────────────┐
    │                  HANDOFF PACKAGE                        │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  USER PROFILE (for personalization):                    │
    │  • Role: Product Manager                                │
    │  • Experience: Intermediate with similar tools          │
    │  • Communication: Prefers concise responses             │
    │  • Goals: Research organization, team alignment         │
    │                                                         │
    │  CONTEXT (for first real session):                      │
    │  • First task: Import user interviews                   │
    │  • Features toured: Import, Tagging, Search             │
    │  • Features skipped: API, Integrations                  │
    │  • Questions asked: About bulk import                   │
    │                                                         │
    │  RECOMMENDATIONS (for main agent):                      │
    │  • Start with import wizard                             │
    │  • Offer tagging suggestions proactively                │
    │  • Keep explanations brief                              │
    │  • Team features relevant but secondary                 │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    # Code example
    print("\n💻 HANDOFF CODE:")
    print("-" * 40)
    print("""
    def complete_onboarding(onboarding_machine, main_agent_machine):
        '''Transfer learnings from onboarding to main agent.'''
        
        # User profile transfers automatically (same user_id)
        
        # Create handoff summary in session context
        handoff_summary = {
            "onboarding_completed": True,
            "completed_at": datetime.now().isoformat(),
            "first_recommended_action": "import_wizard",
            "user_expertise_level": "intermediate",
            "communication_preference": "concise",
            "toured_features": ["import", "tagging", "search"],
            "expressed_goals": ["research_organization", "team_alignment"]
        }
        
        # Main agent can read this on first interaction
        return handoff_summary
    """)


# =============================================================================
# PATTERN EXTRACTION
# =============================================================================


def demo_pattern_extraction():
    """Show how onboarding insights improve the product."""

    print("\n" + "=" * 60)
    print("PATTERN EXTRACTION DEMO")
    print("=" * 60)

    print("""
    learned_knowledge captures onboarding patterns:
    
    ┌─────────────────────────────────────────────────────────┐
    │  Namespace: onboarding:patterns                         │
    ├─────────────────────────────────────────────────────────┤
    │                                                         │
    │  COMMON PATHS:                                          │
    │  • 45% of PMs go: Welcome → Team → Import → Tags        │
    │  • 30% of devs go: Welcome → API → Integrations         │
    │  • Enterprise users always ask about SSO first          │
    │                                                         │
    │  DROP-OFF POINTS:                                       │
    │  • 20% drop at "team invite" step                       │
    │  • Pricing page causes 15% to pause                     │
    │                                                         │
    │  SUCCESSFUL PATTERNS:                                   │
    │  • Users who complete tour have 3x retention            │
    │  • Quick wins in first 5 min correlate with activation  │
    │  • Personalized examples increase completion 25%        │
    │                                                         │
    │  COMMON QUESTIONS:                                      │
    │  • "Can I import from Notion?" (add to FAQ)             │
    │  • "Is there a mobile app?" (feature request signal)    │
    │  • "How does pricing work for teams?" (pricing clarity) │
    │                                                         │
    └─────────────────────────────────────────────────────────┘
    """)

    print("\n📈 USING PATTERNS:")
    print("-" * 40)
    print("""
    1. OPTIMIZE FLOW:
       - Reorder steps based on success patterns
       - Add shortcuts for common paths
       - Remove low-value steps
    
    2. IMPROVE PRODUCT:
       - FAQ additions from common questions
       - Feature prioritization from requests
       - UI improvements at drop-off points
    
    3. PERSONALIZE BETTER:
       - Predict user needs from role
       - Pre-configure based on similar users
       - Suggest features based on goals
    """)


# =============================================================================
# BEST PRACTICES
# =============================================================================


def show_best_practices():
    """Display onboarding agent best practices."""

    print("\n" + "=" * 60)
    print("ONBOARDING AGENT BEST PRACTICES")
    print("=" * 60)

    print("""
    ✅ DO:
    
    1. PROGRESSIVE PROFILING
       - Don't ask everything upfront
       - Learn through natural conversation
       - Infer when possible, confirm when needed
    
    2. CHECKPOINT EVERYTHING
       - Users will abandon and return
       - Make resumption seamless
       - Don't repeat completed steps
    
    3. ADAPT TO SIGNALS
       - Branch based on user type
       - Skip irrelevant sections
       - Personalize examples
    
    4. PREPARE FOR HANDOFF
       - Summarize learnings for main agent
       - Recommend first actions
       - Note communication preferences
    
    5. EXTRACT PATTERNS
       - Track success metrics
       - Identify drop-off points
       - Feed insights back to product
    
    ❌ DON'T:
    
    1. INTERROGATE USERS
       - No rapid-fire questions
       - Mix learning with value delivery
       - Let users skip optional info
    
    2. OVER-PERSONALIZE EARLY
       - Wait until you know user well
       - Generic is fine at start
       - Build personalization over time
    
    3. BLOCK PROGRESS
       - Let users explore freely
       - Onboarding should enable, not gate
       - Optional always beats required
    
    4. FORGET CONTEXT
       - Always use session_context
       - Reference previous answers
       - Show you're listening
    """)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("🎓 ONBOARDING AGENT PATTERN")
    print("=" * 60)
    print("Progressive profiling and adaptive onboarding flows")
    print()

    demo_onboarding_flow()
    demo_adaptive_branching()
    demo_checkpoint_recovery()
    demo_handoff_preparation()
    demo_pattern_extraction()
    show_best_practices()

    print("\n" + "=" * 60)
    print("✅ Onboarding agent pattern complete!")
    print("=" * 60)
