"""
Nested Team History for Members
===============================

Demonstrates `add_team_history_to_members` for nested teams: when a parent team
delegates to a nested sub-team, the sub-team is given ITS OWN prior history
(filtered by the sub-team's id) rather than the root team leader's history.

Key concept: `add_team_history_to_members=True` injects a text summary of past
runs into each delegated task. For a nested sub-team, that summary is now scoped
to the sub-team, so it can recall what it specifically worked on across turns.

Note: a parent can delegate directly to a leaf agent inside a sub-team, so the
instructions below force delegation to the sub-team as a unit — that is the path
that receives the sub-team's own history.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/nested_team_history_to_members.db")

# ---------------------------------------------------------------------------
# Create Nested Sub-Team
# ---------------------------------------------------------------------------
analyst = Agent(
    name="Research Analyst",
    model=OpenAIResponses(id="gpt-5.5"),
    role="Research a topic and report a concise finding",
)

research_team = Team(
    name="Research Team",
    id="research_team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[analyst],
    role="Handle all research requests",
)

# ---------------------------------------------------------------------------
# Create Parent Team
# ---------------------------------------------------------------------------
main_team = Team(
    name="Main Team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[research_team],
    db=db,
    add_team_history_to_members=True,  # Share history with members
    num_team_history_runs=5,
    instructions=[
        "You coordinate sub-teams. Delegate every request to the member with id 'research_team' (the Research Team).",
        "Delegate to the team as a whole using member_id='research_team'. Never delegate to an individual agent inside a sub-team.",
    ],
)

# ---------------------------------------------------------------------------
# Run Multi-Turn Conversation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "nested-team-history-to-members"

    # Turn 1: the Research Team investigates a topic
    main_team.print_response(
        "Research the number 7 and report one concise, memorable fact about it.",
        session_id=session_id,
        stream=True,
    )

    # Turn 2: the Research Team should recall its own previous finding
    main_team.print_response(
        "What number did the Research Team research last time, and what fact did it report?",
        session_id=session_id,
        stream=True,
    )
