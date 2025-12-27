"""
This example demonstrates a team where the team leader routes requests to the appropriate member, and the members respond directly to the user.

In addition each team member has access to the shared history of the team.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

german_agent = Agent(
    name="German Agent",
    role="You answer German questions.",
    model=OpenAIChat(id="o3-mini"),
)

spanish_agent = Agent(
    name="Spanish Agent",
    role="You answer Spanish questions.",
    model=OpenAIChat(id="o3-mini"),
)


multi_lingual_q_and_a_team = Team(
    name="Multi Lingual Q and A Team",
    model=OpenAIChat("o3-mini"),
    members=[german_agent, spanish_agent],
    instructions=[
        "You are a multi lingual Q and A team that can answer questions in English and Spanish. You MUST delegate the task to the appropriate member based on the language of the question.",
        "If the question is in German, delegate to the German agent. If the question is in Spanish, delegate to the Spanish agent.",
        "Always translate the response from the appropriate language to English and show both the original and translated responses.",
    ],
    db=SqliteDb(
        db_file="tmp/multi_lingual_q_and_a_team.db"
    ),  # Add a database to store the conversation history. This is a requirement for history to work correctly.
    determine_input_for_members=False,  # Send the input directly to the member agents without the team leader synthesizing its own input.
    respond_directly=True,
    add_team_history_to_members=True,  # Send all interactions between the user and the team to the member agents.
)


session_id = f"conversation_{uuid4()}"

# First give information to the team
## Ask question in German
multi_lingual_q_and_a_team.print_response(
    "Hallo, wie heißt du? Meine Name ist John.", stream=True, session_id=session_id
)

# Then watch them recall the information (the question below states: "Tell me a 2-sentence story using my name")
## Follow up in Spanish
multi_lingual_q_and_a_team.print_response(
    "Cuéntame una historia de 2 oraciones usando mi nombre real.",
    stream=True,
    session_id=session_id,
)
