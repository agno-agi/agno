"""
Gemini Interactions - Deep Research with Collaborative Planning
================================================================

Human-in-the-loop research: the agent proposes a plan, you refine it, then
you approve it to run the full research.

Flow (all turns share one session so previous_interaction_id chains):
  1. collaborative_planning=True  -> agent returns a research PLAN
  2. collaborative_planning=True  -> refine the plan (optional)
  3. collaborative_planning=False -> agent EXECUTES the approved plan

`collaborative_planning` is a model-construction field, so to flip it from
plan-mode to execute-mode within one conversation we mutate
`agent.model.collaborative_planning` between turns. The field is read fresh
on every request, and `previous_interaction_id` is derived from message
history (not the flag), so the conversation stays linked across the change.

Trade-off: mutating a model field mid-conversation works but is only safe
when the model instance is not shared across concurrent runs. For concurrent
use, prefer two separate agents (a planner and an executor) sharing a session.

Deep Research runs in the background; the model forces background execution
and polls until the result is ready.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import GeminiInteractions

# add_history_to_context + db are required so each turn carries the prior
# assistant message (and its interaction id) for previous_interaction_id chaining.
agent = Agent(
    model=GeminiInteractions(
        agent="deep-research-preview-04-2026",
        collaborative_planning=True,
        thinking_summaries="auto",
        agent_poll_interval=5.0,
    ),
    add_history_to_context=True,
    db=SqliteDb(db_file="tmp/deep_research_collab.db"),
    markdown=True,
)

SESSION_ID = "deep-research-collab-1"

if __name__ == "__main__":
    # Step 1: request a research plan (collaborative_planning=True)
    agent.print_response(
        "Do some research on Google TPUs.",
        session_id=SESSION_ID,
    )

    # Step 2 (optional): refine the plan, still in planning mode
    agent.print_response(
        "Focus more on the differences between Google TPUs and competitor "
        "hardware, and less on the history.",
        session_id=SESSION_ID,
    )

    # Step 3: approve and execute. Flip to execute-mode before this turn.
    agent.model.collaborative_planning = False
    agent.print_response(
        "Plan looks good!",
        session_id=SESSION_ID,
    )
