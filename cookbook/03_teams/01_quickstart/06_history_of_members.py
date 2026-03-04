"""
History Of Members
=============================

Demonstrates member-level history where each member tracks its own prior context.
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
    model=OpenAIResponses(id="gpt-5.2"),
    add_history_to_context=True,  # The member will have access to it's own history.
)

spanish_agent = Agent(
    name="Spanish Agent",
    role="You answer Spanish questions.",
    model=OpenAIResponses(id="gpt-5.2"),
    add_history_to_context=True,  # The member will have access to it's own history.
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
multi_lingual_q_and_a_team = Team(
    name="Multi Lingual Q and A Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[german_agent, spanish_agent],
    instructions=[
        "You are a multi lingual Q and A team that can answer questions in English and Spanish. You MUST delegate the task to the appropriate member based on the language of the question.",
        "If the question is in German, delegate to the German agent. If the question is in Spanish, delegate to the Spanish agent.",
    ],
    db=SqliteDb(
        db_file="tmp/multi_lingual_q_and_a_team.db"
    ),  # Add a database to store the conversation history. This is a requirement for history to work correctly.
    determine_input_for_members=False,  # Send input directly to member agents.
    mode=TeamMode.route,  # Return member responses directly to the user.
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = f"conversation_{uuid4()}"

    # Ask question in German
    multi_lingual_q_and_a_team.print_response(
        "Hallo, wie heißt du? Mein Name ist John.",
        stream=True,
        session_id=session_id,
    )

    # Follow up in German
    multi_lingual_q_and_a_team.print_response(
        "Erzähl mir eine Geschichte mit zwei Sätzen und verwende dabei meinen richtigen Namen.",
        stream=True,
        session_id=session_id,
    )

    # Ask question in Spanish
    multi_lingual_q_and_a_team.print_response(
        "Hola, ¿cómo se llama? Mi nombre es Juan.",
        stream=True,
        session_id=session_id,
    )

    # Follow up in Spanish
    multi_lingual_q_and_a_team.print_response(
        "Cuenta una historia de dos oraciones y utiliza mi nombre real.",
        stream=True,
        session_id=session_id,
    )
