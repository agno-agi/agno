"""
Plan and Learn Agent (PaL) — Using LearningMachine
===================================================
A disciplined planning and execution agent that:
- Creates structured plans with success criteria
- Executes steps sequentially with verification
- Learns from successful executions
- Persists state across sessions

This version uses LearningMachine instead of manual state management.

The original PaL implementation (shared in context) used:
- Manual session_state for plan tracking
- Manual Knowledge() calls for learnings
- Custom tool functions for everything

This implementation shows how LearningMachine provides:
- SessionContextStore with planning mode → replaces manual plan state
- LearningsStore → replaces manual knowledge management
- UserProfileStore → adds user preference tracking (bonus!)

> Plan. Execute. Learn. Repeat.

Run this example:
    python cookbook/learning/11_plan_and_learn_agent.py
"""

from datetime import datetime, timezone
from typing import List, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import (
    LearningMachine,
    LearningMode,
    LearningsConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.pgvector import PgVector, SearchType

# =============================================================================
# Configuration
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# Knowledge base for execution learnings
execution_kb = Knowledge(
    name="PaL Execution Learnings",
    vector_db=PgVector(
        db_url=db_url,
        table_name="pal_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


# =============================================================================
# Planning Tools (Simplified with LearningMachine)
# =============================================================================
#
# With LearningMachine's SessionContextStore in planning mode, we get:
# - goal: The overall objective
# - plan: List of steps
# - progress: Current status
#
# The agent updates these via natural conversation, and SessionContextStore
# extracts and persists them automatically.
#
# We still provide explicit tools for structured plan management.
# =============================================================================


def create_plan(
    run_context: RunContext,
    objective: str,
    steps: List[str],
    context: Optional[str] = None,
) -> str:
    """
    Create an execution plan with ordered steps.

    Args:
        objective: The overall goal to achieve
        steps: List of step descriptions (success criteria inferred)
        context: Optional background information

    Example:
        create_plan(
            objective="Competitive analysis of cloud storage",
            steps=[
                "Identify top 3 providers by market share",
                "Compare pricing tiers across all providers",
                "Analyze key features and differentiators",
                "Write executive summary with recommendations",
            ]
        )
    """
    state = run_context.session_state

    # Guard: Don't overwrite active plan
    if state.get("plan") and state.get("status") == "in_progress":
        return (
            "⚠️ A plan is already in progress.\n"
            "Complete current plan or use reset_plan() to start fresh."
        )

    # Build plan structure
    plan_items = []
    for i, step_desc in enumerate(steps, 1):
        plan_items.append(
            {
                "id": i,
                "description": step_desc.strip(),
                "status": "pending",
                "completed_at": None,
                "output": None,
            }
        )

    # Initialize state
    state["objective"] = objective.strip()
    state["context"] = context.strip() if context else None
    state["plan"] = plan_items
    state["current_step"] = 1
    state["status"] = "in_progress"
    state["created_at"] = datetime.now(timezone.utc).isoformat()

    # Format response
    steps_display = "\n".join([f"  {i}. {s}" for i, s in enumerate(steps, 1)])

    return (
        f"✅ Plan created!\n\n"
        f"🎯 **Objective**: {objective}\n"
        f"{'📝 Context: ' + context + chr(10) if context else ''}\n"
        f"**Steps**:\n{steps_display}\n\n"
        f"→ Ready to begin with Step 1"
    )


def complete_step(run_context: RunContext, output: str) -> str:
    """
    Mark the current step as complete with results.

    Args:
        output: Evidence/results demonstrating completion
    """
    state = run_context.session_state
    plan = state.get("plan", [])
    current = state.get("current_step", 1)

    if not plan:
        return "❌ No plan exists. Create one first with create_plan()."

    if state.get("status") == "complete":
        return "✅ Plan is already complete. Use reset_plan() to start a new one."

    # Mark current step complete
    step = plan[current - 1]
    step["status"] = "complete"
    step["completed_at"] = datetime.now(timezone.utc).isoformat()
    step["output"] = output.strip()

    # Check if this was the last step
    if current >= len(plan):
        state["status"] = "complete"
        return (
            f"✅ Step {current} complete!\n\n"
            f"🎉 **Plan Finished!** All {len(plan)} steps done.\n\n"
            f"💡 Consider: Is there a reusable insight from this execution?\n"
            f"If so, use `save_learning()` to store it for future tasks."
        )

    # Advance to next step
    state["current_step"] = current + 1
    next_step = plan[current]

    return (
        f"✅ Step {current} complete!\n\n"
        f"→ **Step {current + 1}**: {next_step['description']}"
    )


def get_plan_status(run_context: RunContext) -> str:
    """Get a formatted view of the current plan status."""
    state = run_context.session_state

    if not state.get("plan"):
        return "📋 No active plan. Use create_plan() to start."

    objective = state["objective"]
    plan = state["plan"]
    current = state["current_step"]
    status = state["status"]

    # Build output
    lines = [
        f"🎯 **Objective**: {objective}",
        f"📊 **Status**: {status.upper()}",
        "",
        "**Steps**:",
    ]

    for s in plan:
        icon = "✓" if s["status"] == "complete" else "○"
        marker = (
            " ◀ CURRENT" if s["id"] == current and s["status"] != "complete" else ""
        )
        lines.append(f"  {icon} [{s['id']}] {s['description']}{marker}")

    # Progress bar
    done = sum(1 for s in plan if s["status"] == "complete")
    total = len(plan)
    pct = int(done / total * 100) if total > 0 else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)

    lines.extend(["", f"Progress: [{bar}] {done}/{total} ({pct}%)"])

    return "\n".join(lines)


def reset_plan(run_context: RunContext) -> str:
    """Clear the current plan to start fresh."""
    state = run_context.session_state
    state.update(
        {
            "objective": None,
            "context": None,
            "plan": [],
            "current_step": 1,
            "status": "no_plan",
            "created_at": None,
        }
    )
    return "🗑️ Plan cleared. Ready to create a new plan."


# =============================================================================
# Agent Instructions
# =============================================================================

INSTRUCTIONS = """\
You are **PaL** — the **Plan and Learn** Agent.

A friendly, helpful assistant that tackles complex multi-step tasks with discipline.

## WHEN TO PLAN

**Create a plan** for tasks that:
- Have multiple distinct steps
- Need to be done in a specific order
- Would benefit from tracking progress

**Don't plan** for:
- Simple questions → just answer
- Quick tasks → just do them
- Casual conversation → just chat

## CURRENT STATE

Objective: {objective}
Step: {current_step} of {plan_length}
Status: {status}

## THE PaL CYCLE

1. **PLAN** — Break goals into steps with `create_plan()`
2. **EXECUTE** — Work through steps, call `complete_step()` with evidence
3. **ADAPT** — Plans can evolve as you learn
4. **LEARN** — After success, save reusable insights with `save_learning()`

## EXECUTION RULES

- Complete step N before starting N+1
- Call `complete_step()` with evidence of completion
- Use `get_plan_status()` to check progress

## YOUR KNOWLEDGE

You have learnings from past executions. When planning:
- Search for relevant patterns with `search_learnings()`
- Apply what worked before
- Save new insights that could help future tasks

## PERSONALITY

You're a PaL — friendly, helpful, and disciplined when it matters.
- Chat naturally for simple stuff
- Get structured when complexity requires it
- Learn and improve over time
"""


# =============================================================================
# Create the Agent
# =============================================================================

pal_agent = Agent(
    id="plan-and-learn-agent",
    name="PaL (Plan and Learn Agent)",
    model=model,
    instructions=INSTRUCTIONS,
    db=db,
    # Planning tools
    tools=[
        create_plan,
        complete_step,
        get_plan_status,
        reset_plan,
        # Execution tools
        YFinanceTools(
            stock_price=True,
            company_info=True,
            analyst_recommendations=True,
        ),
    ],
    # Session state for plan tracking
    session_state={
        "objective": None,
        "context": None,
        "plan": [],
        "plan_length": 0,
        "current_step": 1,
        "status": "no_plan",
        "created_at": None,
    },
    add_session_state_to_context=True,
    # LearningMachine for persistence and learning
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=execution_kb,
        # User profiles: Remember user preferences
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            enable_tool=True,
        ),
        # Session context: Track plan state (planning mode!)
        session_context=SessionContextConfig(
            enable_planning=True,  # This is key for PaL!
        ),
        # Learnings: Agent saves execution insights
        learnings=LearningsConfig(
            mode=LearningMode.AGENTIC,
            enable_tool=True,
            enable_search=True,
        ),
    ),
    # Context management
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)


# =============================================================================
# CLI Interface
# =============================================================================


def run_pal(message: str, session_id: Optional[str] = None, user_id: str = "pal_user"):
    """Run PaL with a message."""
    pal_agent.print_response(
        message,
        session_id=session_id,
        user_id=user_id,
        stream=True,
    )

    # Show state after response
    state = pal_agent.get_session_state()
    print(f"\n{'─' * 40}")
    print(f"📊 Status: {state.get('status', 'no_plan')}")
    if state.get("plan"):
        done = sum(1 for s in state["plan"] if s["status"] == "complete")
        print(f"   Progress: {done}/{len(state['plan'])} steps")
    print(f"{'─' * 40}")


def demo_planning():
    """Demonstrate the planning workflow."""
    print("=" * 60)
    print("🤝 PaL — Plan and Learn Agent Demo")
    print("=" * 60)

    session_id = f"pal_demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Step 1: Create a plan
    print("\n" + "─" * 50)
    print("📝 Step 1: Create a Plan")
    print("─" * 50)

    run_pal(
        "I want to analyze Apple stock (AAPL) for a potential investment. "
        "Help me create a structured plan.",
        session_id=session_id,
    )

    # Step 2: Execute first step
    print("\n" + "─" * 50)
    print("📝 Step 2: Execute First Step")
    print("─" * 50)

    run_pal(
        "Let's start with step 1. Get the current price and basic info.",
        session_id=session_id,
    )

    # Step 3: Continue execution
    print("\n" + "─" * 50)
    print("📝 Step 3: Continue Execution")
    print("─" * 50)

    run_pal(
        "Great! Now let's check the analyst recommendations.",
        session_id=session_id,
    )

    # Step 4: Check status
    print("\n" + "─" * 50)
    print("📝 Step 4: Check Status")
    print("─" * 50)

    run_pal("What's our progress so far?", session_id=session_id)

    print("\n" + "=" * 60)
    print("Demo complete! PaL tracked the plan and can resume later.")
    print("=" * 60)


def interactive():
    """Run PaL interactively."""
    print("=" * 60)
    print("🤝 PaL — Plan and Learn Agent")
    print("   Plan. Execute. Learn. Repeat.")
    print("=" * 60)
    print("\nType 'quit' to exit, 'status' for plan status.\n")

    session_id = f"pal_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    user_id = "interactive_user"

    while True:
        try:
            user_input = input("\n👤 You: ").strip()

            if user_input.lower() in ("quit", "exit", "q"):
                print("\n👋 Goodbye! Your plan is saved.")
                break

            if user_input.lower() == "status":
                state = pal_agent.get_session_state()
                if state.get("plan"):
                    print(f"\n🎯 Objective: {state.get('objective')}")
                    print(f"📊 Status: {state.get('status')}")
                    for s in state["plan"]:
                        icon = "✓" if s["status"] == "complete" else "○"
                        print(f"   {icon} {s['id']}. {s['description']}")
                else:
                    print("\n📋 No active plan")
                continue

            if user_input.lower() == "debug":
                learning = pal_agent.learning
                print(f"\n📊 LearningMachine: {learning}")
                for name, store in learning.stores.items():
                    print(f"   {name}: {store}")
                continue

            if not user_input:
                continue

            print()
            run_pal(user_input, session_id=session_id, user_id=user_id)

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "demo":
            demo_planning()
        elif sys.argv[1] == "interactive":
            interactive()
        else:
            # Run with command line argument
            message = " ".join(sys.argv[1:])
            run_pal(message)
    else:
        print("=" * 60)
        print("🤝 PaL — Plan and Learn Agent")
        print("=" * 60)
        print("\nUsage:")
        print("  python 11_plan_and_learn_agent.py demo        — Run demo")
        print("  python 11_plan_and_learn_agent.py interactive — Chat mode")
        print("  python 11_plan_and_learn_agent.py <message>   — Single query")
        print("\nRunning interactive mode by default...\n")
        interactive()
