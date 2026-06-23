"""
Gemini Interactions - Deep Research multi-turn
===============================================

Continue a Deep Research interaction across turns. Each response carries an
interaction_id; the next turn references it via `previous_interaction_id`
so the API only receives the new user message (the server already has the
prior research and its citations).

Persisting the interaction_id requires a db (e.g. SqliteDb): the assistant
message stores it under provider_data, and the next turn reads it back.

A common Deep Research multi-turn flow:
  1. Turn 1: ask for a plan (collaborative_planning=True returns just the plan)
  2. Turn 2: approve or refine the plan
  3. Turn 3+: drill into specific sections of the report

For the dedicated plan/approve flow see deep_research_collaborative_planning.py.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import GeminiInteractions

agent = Agent(
    model=GeminiInteractions(
        agent="deep-research-preview-04-2026",
        thinking_summaries="auto",
    ),
    add_history_to_context=True,
    db=SqliteDb(db_file="tmp/data.db"),
    markdown=True,
)

if __name__ == "__main__":
    # Turn 1 - kick off the research task.
    agent.print_response(
        "Research the current state of solid-state battery commercialization "
        "and summarize the leading approaches."
    )

    # Turn 2 - drill into one approach. The server has the prior research;
    # only this question is sent on the wire.
    agent.print_response(
        "Dive deeper into the sulfide-electrolyte approach: who the leading "
        "labs and companies are, and what their reported milestones look like."
    )

    # Turn 3 - synthesize across turns.
    agent.print_response(
        "Based on everything we've covered, which approach has the clearest "
        "path to mass-market EV deployment in the next five years?"
    )
