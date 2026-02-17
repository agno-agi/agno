"""
Team History
=============================

Demonstrates sharing team history with member agents across a session.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team, TeamMode

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
german_agent = Agent(
    name="German Agent",
    role="You answer German questions.",
    model=OpenAIResponses(id="gpt-5-mini"),
)

spanish_agent = Agent(
    name="Spanish Agent",
    role="You answer Spanish questions.",
    model=OpenAIResponses(id="gpt-5-mini"),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
multi_lingual_q_and_a_team = Team(
    name="Multi Lingual Q and A Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[german_agent, spanish_agent],
    instructions=[
        "You are a multi lingual Q and A team that can answer questions in English and Spanish. You MUST delegate the task to the appropriate member based on the language of the question.",
        "If the question is in German, delegate to the German agent. If the question is in Spanish, delegate to the Spanish agent.",
        "Always translate the response from the appropriate language to English and show both the original and translated responses.",
    ],
    db=SqliteDb(
        db_file="tmp/multi_lingual_q_and_a_team.db"
    ),  # Add a database to store the conversation history. This is a requirement for history to work correctly.
    determine_input_for_members=False,  # Send input directly to members.
    mode=TeamMode.route,
    add_team_history_to_members=True,  # Send all interactions between the user and the team to the member agents.
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = f"conversation_{uuid4()}"

    # First give information to the team
    # Ask question in German
    multi_lingual_q_and_a_team.print_response(
        "Hallo, wie heißt du? Meine Name ist John.",
        stream=True,
        session_id=session_id,
    )

    # Then watch them recall the information (the question below states:
    # "Tell me a 2-sentence story using my name")
    # Follow up in Spanish
    multi_lingual_q_and_a_team.print_response(
        "Cuéntame una historia de 2 oraciones usando mi nombre real.",
        stream=True,
        session_id=session_id,
    )
