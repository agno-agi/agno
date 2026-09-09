"""
Nested Team History
===================

Demonstrates how nested teams (teams as members of other teams) maintain
their own conversation history across multiple delegations.

Key concept: When a parent team delegates to a nested team, the nested team
receives its previous conversation history via `add_history_to_context=True`.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/nested_team_history.db")

# ---------------------------------------------------------------------------
# Create Nested Team
# ---------------------------------------------------------------------------
analyst = Agent(
    name="Data Analyst",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    role="Analyze data and provide insights",
)

research_team = Team(
    name="Research Team",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    members=[analyst],
    add_history_to_context=True,
    role="Conduct research and analysis",
)

# ---------------------------------------------------------------------------
# Create Parent Team
# ---------------------------------------------------------------------------
writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    role="Write and format outputs",
)

main_team = Team(
    name="Main Team",
    model=OpenAIResponses(id="gpt-5.6-sol"),
    members=[writer, research_team],
    db=db,
    add_history_to_context=True,
    mode="route",
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Multi-Turn Conversation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "nested-team-demo"

    # Turn 1: Research request
    main_team.print_response(
        "Research the top 3 benefits of AI coding assistants",
        session_id=session_id,
        stream=True,
    )

    # Turn 2: Follow-up - research team should remember Turn 1
    main_team.print_response(
        "Based on your research, which benefit is best for startups?",
        session_id=session_id,
        stream=True,
    )

    # Turn 3: Another follow-up
    main_team.print_response(
        "What challenges might startups face adopting that?",
        session_id=session_id,
        stream=True,
    )
