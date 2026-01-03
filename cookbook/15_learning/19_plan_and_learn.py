"""
Plan and Learn Agent (PaL)
===========================================
The Plan and Learn pattern combines:
1. Structured planning (goal → plan → execution → progress)
2. Learning from outcomes (what worked, what didn't)

This creates a powerful loop:
- Plan: Break down complex tasks
- Execute: Work through steps
- Learn: Capture what worked for future plans

Over time, the agent gets better at BOTH planning AND execution.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import (
    LearningMachine,
    LearningMode,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=db_url, table_name="pal_learnings"),
)

# =============================================================================
# PaL Instructions
# =============================================================================
INSTRUCTIONS = """\
You are a Plan and Learn (PaL) Agent. You break down complex tasks,
execute them step by step, and learn from the outcomes.

## The PaL Loop

### 1. PLAN
When given a complex task:
- Search learnings for relevant planning patterns
- Break it into clear, sequential steps
- Identify potential blockers early
- Set clear success criteria

### 2. EXECUTE
For each step:
- Explain what you're doing
- Do the work
- Verify completion
- Note any issues encountered

### 3. LEARN
After completion (or failure):
- What worked well?
- What was harder than expected?
- What would you do differently?
- Save valuable patterns as learnings

## Planning Patterns to Learn

Save learnings about:
- Task decomposition strategies
- Common pitfalls and how to avoid them
- Effective step sequencing
- Time/effort estimates that proved accurate

## Example

User: "Help me set up CI/CD for my Python project"

PLAN:
1. Understand project structure (5 min)
2. Choose CI platform (GitHub Actions recommended)
3. Create workflow file
4. Set up testing stage
5. Add deployment stage
6. Test the pipeline

EXECUTE: [Work through each step]

LEARN: "For Python CI/CD setup, start with a minimal workflow 
that just runs tests. Add complexity incrementally. Common 
gotcha: forgetting to set up Python version matrix."
"""

# =============================================================================
# Create PaL Agent
# =============================================================================
pal_agent = Agent(
    name="Plan and Learn Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=INSTRUCTIONS,
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o-mini"),
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
        ),
        session_context=SessionContextConfig(
            enable_planning=True,  # KEY: Track goal/plan/progress
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helpers
# =============================================================================
def show_plan_state(session_id: str):
    """Show current planning state."""
    context = pal_agent.learning.stores["session_context"].get(session_id=session_id)
    if context:
        print(f"\n📋 Plan State:")
        if context.goal:
            print(f"   🎯 Goal: {context.goal}")
        if context.plan:
            print(f"   📝 Plan:")
            for i, step in enumerate(context.plan, 1):
                print(f"      {i}. {step}")
        if context.progress:
            print(f"   ✅ Progress:")
            for item in context.progress:
                print(f"      ✓ {item}")
    print()


def show_planning_learnings():
    """Show learned planning patterns."""
    results = pal_agent.learning.stores["learned_knowledge"].search(
        query="planning strategy task decomposition",
        limit=5,
    )
    if results:
        print(f"\n📚 Planning Patterns Learned:")
        for r in results:
            title = getattr(r, 'title', 'Untitled')
            print(f"   > {title}")
    print()


# =============================================================================
# Demo: Complete PaL workflow
# =============================================================================
if __name__ == "__main__":
    user_id = "developer@example.com"
    session_id = "pal_demo"

    # --- Step 1: Define a complex task ---
    print("=" * 60)
    print("Step 1: Define Complex Task")
    print("=" * 60)
    pal_agent.print_response(
        "I need to migrate our monolith to microservices. It's a Django app "
        "with about 50k lines of code, handling users, payments, and inventory. "
        "Help me plan this out.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_plan_state(session_id)

    # --- Step 2: Execute first step ---
    print("=" * 60)
    print("Step 2: Execute First Step")
    print("=" * 60)
    pal_agent.print_response(
        "Let's start with step 1. I've identified these bounded contexts: "
        "User Management, Payment Processing, Inventory, and Order Fulfillment. "
        "Does this look right?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_plan_state(session_id)

    # --- Step 3: Handle a blocker ---
    print("=" * 60)
    print("Step 3: Handle a Blocker")
    print("=" * 60)
    pal_agent.print_response(
        "We hit an issue - the payments code is tightly coupled with user "
        "authentication. Every payment function imports the User model directly. "
        "How should we handle this?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_plan_state(session_id)

    # --- Step 4: Complete and reflect ---
    print("=" * 60)
    print("Step 4: Complete and Reflect")
    print("=" * 60)
    pal_agent.print_response(
        "We've successfully extracted the User Management service. It took "
        "longer than expected because of the coupling issue. What did we learn "
        "from this that we should remember for future microservice migrations?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_planning_learnings()

    # --- Later: New task benefits from learnings ---
    print("=" * 60)
    print("Later: New Task Benefits from Learnings")
    print("=" * 60)
    pal_agent.print_response(
        "I have another Django monolith to migrate at my new job. "
        "What should I watch out for based on past experience?",
        user_id="new_developer@example.com",  # Different user!
        session_id="new_migration",
        stream=True,
    )

    # --- Summary ---
    print("=" * 60)
    print("PaL Pattern Summary")
    print("=" * 60)
    print("""
    The Plan and Learn pattern creates a virtuous cycle:
    
    1. PLAN with accumulated wisdom
       - Search for relevant planning patterns
       - Apply lessons from past projects
    
    2. EXECUTE with tracking
       - Session context tracks goal/plan/progress
       - Blockers are captured and addressed
    
    3. LEARN from outcomes
       - What worked gets saved
       - Future plans benefit from experience
    
    Over time, the agent becomes an expert planner!
    """)
