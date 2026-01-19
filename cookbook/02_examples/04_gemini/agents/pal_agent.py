"""
PaL — Plan and Learn Agent
===========================
A disciplined planning and execution agent that:
- Creates structured plans with success criteria
- Executes steps sequentially with verification
- Learns from successful executions
- Persists state across sessions

> Plan. Execute. Learn. Repeat.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional

from agno.agent import Agent
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.models.google import Gemini
from agno.run import RunContext
from agno.tools.parallel import ParallelTools
from agno.tools.yfinance import YFinanceTools
from agno.utils.log import logger
from agno.vectordb.pgvector import PgVector, SearchType
from db import db_url, gemini_agents_db

# ============================================================================
# Knowledge Base: Stores execution learnings
# ============================================================================
execution_knowledge = Knowledge(
    name="PaL Execution Learnings",
    vector_db=PgVector(
        db_url=db_url,
        table_name="pal_execution_learnings",
        search_type=SearchType.hybrid,
        embedder=GeminiEmbedder(id="gemini-embedding-001"),
    ),
    max_results=5,
    contents_db=gemini_agents_db,
)


# ============================================================================
# Planning Tools
# ============================================================================
def create_plan(
    run_context: RunContext,
    objective: str,
    steps: List[dict],
    context: Optional[str] = None,
) -> str:
    """
    Create an execution plan with ordered steps and success criteria.

    Args:
        objective: The overall goal to achieve
        steps: List of step objects, each with:
               - description (str): What to do
               - success_criteria (str): How to verify completion
        context: Optional background information

    Example:
        create_plan(
            objective="Competitive analysis of cloud storage",
            steps=[
                {"description": "Identify top 3 providers", "success_criteria": "List with market share data"},
                {"description": "Compare pricing tiers", "success_criteria": "Pricing table for all tiers"},
                {"description": "Analyze features", "success_criteria": "Feature matrix with 10+ attributes"},
                {"description": "Write summary", "success_criteria": "Executive summary under 500 words"},
            ]
        )
    """
    state = run_context.session_state

    # Guard: Don't overwrite active plan
    if state.get("plan") and state.get("status") == "in_progress":
        return (
            "⚠️ A plan is already in progress.\n"
            "Options:\n"
            "  - Complete the current plan\n"
            "  - Call reset_plan(confirm=True) to start fresh"
        )

    # Validate and build plan structure
    plan_items = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict) or "description" not in step:
            return f"❌ Invalid step format at position {i}. Need {{'description': '...', 'success_criteria': '...'}}"

        plan_items.append(
            {
                "id": i,
                "description": step["description"].strip(),
                "success_criteria": step.get(
                    "success_criteria", "Task completed successfully"
                ).strip(),
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "output": None,
            }
        )

    # Initialize state
    state["objective"] = objective.strip()
    state["context"] = context.strip() if context else None
    state["plan"] = plan_items
    state["plan_length"] = len(plan_items)
    state["current_step"] = 1
    state["status"] = "in_progress"
    state["created_at"] = datetime.now(timezone.utc).isoformat()
    state["completed_at"] = None

    # Format response
    steps_display = "\n".join(
        [
            f"  {s['id']}. {s['description']}\n     ✓ Done when: {s['success_criteria']}"
            for s in plan_items
        ]
    )

    logger.info(f"[PaL] Plan created: {objective} ({len(plan_items)} steps)")

    return (
        f"✅ Plan created!\n\n"
        f"🎯 Objective: {objective}\n"
        f"{'📝 Context: ' + context + chr(10) if context else ''}\n"
        f"Steps:\n{steps_display}\n\n"
        f"→ Ready to begin with Step 1"
    )


def complete_step(run_context: RunContext, output: str) -> str:
    """
    Mark the current step as complete with verification output.

    The output should demonstrate that the success criteria has been met.
    The agent will automatically advance to the next step.

    Args:
        output: Evidence/results that satisfy the step's success criteria
    """
    state = run_context.session_state
    plan = state.get("plan", [])
    current = state.get("current_step", 1)

    if not plan:
        return "❌ No plan exists. Create one first with create_plan()."

    if state.get("status") == "complete":
        return "✅ Plan is already complete. Use reset_plan(confirm=True) to start a new one."

    # Get current step
    step = plan[current - 1]

    if step["status"] == "complete":
        return f"❌ Step {current} is already complete."

    # Mark complete
    now = datetime.now(timezone.utc).isoformat()
    step["status"] = "complete"
    step["completed_at"] = now
    step["output"] = output.strip()

    logger.info(f"[PaL] Step {current} completed: {step['description'][:50]}...")

    # Check if this was the last step
    if current >= len(plan):
        state["status"] = "complete"
        state["completed_at"] = now

        # Calculate duration
        created = datetime.fromisoformat(state["created_at"].replace("Z", "+00:00"))
        completed = datetime.fromisoformat(now.replace("Z", "+00:00"))
        duration = completed - created

        return (
            f"✅ Step {current} complete!\n\n"
            f"🎉 **Plan Finished!**\n"
            f"All {len(plan)} steps completed successfully.\n"
            f"Duration: {duration}\n\n"
            f"💡 **Learning opportunity**: Is there a reusable insight from this execution?\n"
            f"If so, propose it and I'll save it with `save_learning()` for future tasks."
        )

    # Advance to next step
    state["current_step"] = current + 1
    next_step = plan[current]

    return (
        f"✅ Step {current} complete!\n\n"
        f"→ **Step {current + 1}**: {next_step['description']}\n"
        f"  Success criteria: {next_step['success_criteria']}"
    )


def update_plan(
    run_context: RunContext,
    action: str,
    step_id: Optional[int] = None,
    new_step: Optional[dict] = None,
    reason: Optional[str] = None,
) -> str:
    """
    Modify the current plan dynamically.

    Args:
        action: The modification type
                - "add": Append a new step to the end
                - "insert": Insert a step after step_id
                - "remove": Remove a future step
                - "revisit": Go back to a previous step
        step_id: Target step ID (required for insert/remove/revisit)
        new_step: Step definition for add/insert {"description": "...", "success_criteria": "..."}
        reason: Explanation for the change (required for revisit)
    """
    state = run_context.session_state
    plan = state.get("plan", [])
    current = state.get("current_step", 1)

    if not plan:
        return "❌ No plan exists. Create one first."

    # ADD: Append new step to end
    if action == "add":
        if not new_step or "description" not in new_step:
            return (
                "❌ Provide new_step={'description': '...', 'success_criteria': '...'}"
            )

        new_item = {
            "id": len(plan) + 1,
            "description": new_step["description"].strip(),
            "success_criteria": new_step.get(
                "success_criteria", "Task completed"
            ).strip(),
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "output": None,
        }
        plan.append(new_item)
        state["plan_length"] = len(plan)

        logger.info(f"[PaL] Step added: {new_item['description'][:50]}...")
        return f"✅ Added Step {new_item['id']}: {new_item['description']}"

    # INSERT: Add step after a specific position
    elif action == "insert":
        if not step_id or not new_step:
            return "❌ Provide step_id (insert after) and new_step"
        if step_id < current:
            return f"❌ Cannot insert before current step {current}"

        new_item = {
            "id": step_id + 1,
            "description": new_step["description"].strip(),
            "success_criteria": new_step.get(
                "success_criteria", "Task completed"
            ).strip(),
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "output": None,
        }

        # Insert and renumber
        plan.insert(step_id, new_item)
        for i, s in enumerate(plan, 1):
            s["id"] = i
        state["plan_length"] = len(plan)

        logger.info(
            f"[PaL] Step inserted after {step_id}: {new_item['description'][:50]}..."
        )
        return f"✅ Inserted new Step {step_id + 1}: {new_item['description']}"

    # REMOVE: Delete a future step
    elif action == "remove":
        if not step_id:
            return "❌ Provide step_id to remove"
        if step_id <= current:
            return f"❌ Cannot remove step {step_id} — already current or completed"

        removed = next((s for s in plan if s["id"] == step_id), None)
        if not removed:
            return f"❌ Step {step_id} not found"

        state["plan"] = [s for s in plan if s["id"] != step_id]
        # Renumber remaining steps
        for i, s in enumerate(state["plan"], 1):
            s["id"] = i
        state["plan_length"] = len(state["plan"])

        logger.info(f"[PaL] Step removed: {removed['description'][:50]}...")
        return f"✅ Removed: {removed['description']}\nPlan now has {state['plan_length']} steps."

    # REVISIT: Go back to a previous step
    elif action == "revisit":
        if not step_id:
            return "❌ Provide step_id to revisit"
        if not reason:
            return "❌ Provide reason for revisiting"
        if step_id > current:
            return f"❌ Step {step_id} hasn't been reached yet"

        # Reset this step and all subsequent
        for s in plan:
            if s["id"] >= step_id:
                s["status"] = "pending"
                s["started_at"] = None
                s["completed_at"] = None
                if s["id"] == step_id:
                    s["output"] = f"[Revisiting: {reason}]"
                else:
                    s["output"] = None

        state["current_step"] = step_id
        state["status"] = "in_progress"

        logger.info(f"[PaL] Revisiting step {step_id}: {reason}")
        return (
            f"🔄 Revisiting Step {step_id}\n"
            f"Reason: {reason}\n"
            f"Progress reset to this step."
        )

    return f"❌ Unknown action: {action}. Use 'add', 'insert', 'remove', or 'revisit'."


def block_step(
    run_context: RunContext, blocker: str, suggestion: Optional[str] = None
) -> str:
    """
    Mark the current step as blocked with an explanation.

    Args:
        blocker: What is preventing progress
        suggestion: Optional suggested resolution
    """
    state = run_context.session_state
    plan = state.get("plan", [])
    current = state.get("current_step", 1)

    if not plan:
        return "❌ No plan exists."

    step = plan[current - 1]
    step["status"] = "blocked"
    step["output"] = f"BLOCKED: {blocker}"

    logger.warning(f"[PaL] Step {current} blocked: {blocker}")

    response = f"⚠️ Step {current} is blocked\n\n**Blocker**: {blocker}\n"

    if suggestion:
        response += f"**Suggested resolution**: {suggestion}\n"

    response += (
        "\n**Options**:\n"
        "  - Resolve the blocker and call complete_step()\n"
        "  - Use update_plan(action='revisit', ...) to try a different approach\n"
        "  - Use reset_plan(confirm=True) to start over"
    )

    return response


def get_status(run_context: RunContext) -> str:
    """
    Get a formatted view of the current plan status.
    Shows objective, all steps with their status, and progress.
    """
    state = run_context.session_state

    if not state.get("plan"):
        return (
            "📋 No active plan.\n\n"
            "Use create_plan() to start. Example:\n"
            "```\n"
            "create_plan(\n"
            '    objective="Your goal here",\n'
            "    steps=[\n"
            '        {"description": "First step", "success_criteria": "How to verify"},\n'
            '        {"description": "Second step", "success_criteria": "How to verify"},\n'
            "    ]\n"
            ")\n"
            "```"
        )

    objective = state["objective"]
    context = state.get("context")
    plan = state["plan"]
    current = state["current_step"]
    status = state["status"]

    # Status icons
    icons = {
        "pending": "○",
        "complete": "✓",
        "blocked": "✗",
    }

    # Build output
    lines = [
        f"{'═' * 50}",
        f"🎯 OBJECTIVE: {objective}",
        f"📊 STATUS: {status.upper()}",
    ]

    if context:
        lines.append(f"📝 Context: {context}")

    lines.extend(["", "STEPS:", ""])

    for s in plan:
        icon = icons.get(s["status"], "○")
        is_current = s["id"] == current and s["status"] not in ["complete", "blocked"]
        marker = " ◀ CURRENT" if is_current else ""

        lines.append(f"  {icon} [{s['id']}] {s['description']}{marker}")

        if is_current:
            lines.append(f"       ✓ Must satisfy: {s['success_criteria']}")

        if s["output"] and s["status"] == "complete":
            # Truncate long outputs
            output_preview = (
                s["output"][:80] + "..." if len(s["output"]) > 80 else s["output"]
            )
            lines.append(f"       └─ {output_preview}")
        elif s["status"] == "blocked":
            lines.append(f"       └─ {s['output']}")

    # Progress bar
    done = sum(1 for s in plan if s["status"] == "complete")
    total = len(plan)
    pct = int(done / total * 100) if total > 0 else 0
    bar_filled = int(pct / 5)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    lines.extend(
        [
            "",
            f"Progress: [{bar}] {done}/{total} ({pct}%)",
            f"{'═' * 50}",
        ]
    )

    return "\n".join(lines)


def reset_plan(run_context: RunContext, confirm: bool = False) -> str:
    """
    Clear the current plan to start fresh.

    Args:
        confirm: Must be True to actually reset (safety check)
    """
    if not confirm:
        return (
            "⚠️ This will clear the current plan and all progress.\n"
            "To confirm, call: reset_plan(confirm=True)"
        )

    state = run_context.session_state
    state.update(
        {
            "objective": None,
            "context": None,
            "plan": [],
            "plan_length": 0,
            "current_step": 1,
            "status": "no_plan",
            "created_at": None,
            "completed_at": None,
        }
    )

    logger.info("[PaL] Plan reset")
    return "🗑️ Plan cleared. Ready to create a new plan."


# ============================================================================
# Learning Tool
# ============================================================================
def save_learning(
    run_context: RunContext,
    title: str,
    learning: str,
    applies_to: str,
    effectiveness: Optional[str] = "medium",
) -> str:
    """
    Save a reusable learning from this execution for future reference.

    Only save learnings that are:
    - Specific and actionable
    - Applicable to similar future tasks
    - Based on what actually worked

    Args:
        title: Short descriptive name (e.g., "Pricing Research Pattern")
        learning: The actual insight/pattern (be specific!)
        applies_to: What types of tasks this helps with
        effectiveness: How well it worked - "low" | "medium" | "high"

    Example:
        save_learning(
            title="Competitor Pricing Sources",
            learning="For SaaS pricing: 1) Official pricing page, 2) G2/Capterra, 3) PricingBot archives. Official pages often hide enterprise tiers.",
            applies_to="competitive analysis, pricing research, market research",
            effectiveness="high"
        )
    """
    state = run_context.session_state

    payload = {
        "title": title.strip(),
        "learning": learning.strip(),
        "applies_to": applies_to.strip(),
        "effectiveness": effectiveness,
        "source_objective": state.get("objective", "unknown"),
        "source_steps": len(state.get("plan", [])),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(f"[PaL] Saving learning: {payload['title']}")

    try:
        execution_knowledge.add_content(
            name=payload["title"],
            text_content=json.dumps(payload, ensure_ascii=False),
            reader=TextReader(),
            skip_if_exists=True,
        )
        return (
            f"💡 Learning saved!\n\n"
            f"**{title}**\n"
            f"{learning}\n\n"
            f"_Applies to: {applies_to}_"
        )
    except Exception as e:
        logger.error(f"[PaL] Failed to save learning: {e}")
        return f"❌ Failed to save learning: {str(e)}"


# ============================================================================
# Agent Instructions
# ============================================================================
instructions = """\
You are **PaL** — the **Plan and Learn** Agent.

You're a friendly, helpful assistant that can also tackle complex multi-step tasks with discipline. You plan when it's useful, not for everything.

## WHEN TO PLAN

**Create a plan** for tasks that:
- Have multiple distinct steps
- Need to be done in a specific order
- Would benefit from tracking progress
- Are complex enough that you might lose track

**Don't plan** for:
- Simple questions → just answer them
- Quick tasks → just do them
- Casual conversation → just chat
- Single-step requests → just handle them

When in doubt: if you can do it in one response without losing track, skip the plan.

## CURRENT STATE
- Objective: {objective}
- Step: {current_step} of {plan_length}
- Status: {status}

## THE PaL CYCLE (for complex tasks)

1. **PLAN** — Break the goal into steps with success criteria. Call `create_plan()`.
2. **EXECUTE** — Work through steps one at a time. Call `complete_step()` with evidence.
3. **ADAPT** — Add, revisit, or block steps as needed. Plans can evolve.
4. **LEARN** — After success, propose reusable insights. Save only with user approval.

## EXECUTION RULES (when planning)

- Complete step N before starting step N+1
- Verify success criteria before calling `complete_step()`
- Use tools to change state — don't just describe changes

## YOUR KNOWLEDGE BASE

You have learnings from past tasks. When planning something similar:
- Search for relevant patterns
- Apply what worked before
- Mention when a learning influenced your approach

## PERSONALITY

You're a PaL — friendly, helpful, and easy to talk to. You:
- Chat naturally for simple stuff
- Get structured when complexity requires it
- Celebrate progress without being over-the-top
- Push back gently if asked to skip important steps
- Learn and improve over time

Be helpful first. Be disciplined when it matters.\
"""


# ============================================================================
# Create the Agent
# ============================================================================
pal_agent = Agent(
    id="plan-and-learn-agent",
    name="PaL (Plan and Learn Agent)",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    # Database for persistence
    db=gemini_agents_db,
    # Knowledge base for learnings
    knowledge=execution_knowledge,
    search_knowledge=True,
    # Session state structure
    session_state={
        "objective": None,
        "context": None,
        "plan": [],
        "plan_length": 0,
        "current_step": 1,
        "status": "no_plan",
        "created_at": None,
        "completed_at": None,
    },
    tools=[
        # Plan management
        create_plan,
        complete_step,
        update_plan,
        block_step,
        get_status,
        reset_plan,
        # Learning
        save_learning,
        # Execution capabilities
        ParallelTools(),
        YFinanceTools(),
    ],
    # Make state available in instructions
    add_session_state_to_context=True,
    # Enable memory for user preferences
    enable_agentic_memory=True,
    # Context management
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    read_chat_history=True,
    # Output
    markdown=True,
)


# ============================================================================
# CLI Interface
# ============================================================================
def run_pal(message: str, session_id: Optional[str] = None, show_state: bool = True):
    """
    Run PaL with a message, optionally continuing a session.

    Args:
        message: The user's message/request
        session_id: Optional session ID to continue a previous session
        show_state: Whether to print the state after the response
    """
    pal_agent.print_response(message, session_id=session_id, stream=True)
    if show_state:
        state = pal_agent.get_session_state()
        print(f"\n{'─' * 50}")
        print("📊 Session State:")
        print(f"   Status: {state.get('status', 'no_plan')}")
        if state.get("plan"):
            done = sum(1 for s in state["plan"] if s["status"] == "complete")
            print(f"   Progress: {done}/{len(state['plan'])} steps")
        print(f"{'─' * 50}")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Run with command line argument
        message = " ".join(sys.argv[1:])
        run_pal(message)
    else:
        # Interactive mode
        print("=" * 60)
        print("🤝 PaL — Plan and Learn Agent")
        print("   Plan. Execute. Learn. Repeat.")
        print("=" * 60)
        print("\nType 'quit' or 'exit' to stop.\n")

        session_id = f"pal_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        while True:
            try:
                user_input = input("\n👤 You: ").strip()
                if user_input.lower() in ["quit", "exit", "q"]:
                    print("\n👋 Goodbye!")
                    break
                if not user_input:
                    continue

                print()
                run_pal(user_input, session_id=session_id)

            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break
