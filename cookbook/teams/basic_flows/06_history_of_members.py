"""
This example demonstrates a team where the team leader routes requests to the appropriate member, and the members respond directly to the user.

In addition each team member has access to it's own history.
Note: In this example the team leader has no access to the history of the team or the members themselves, so this show-cases how to use the history of the members themselves.
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

german_agent = Agent(
    name="German Agent",
    role="You answer German questions.",
    model=OpenAIChat(id="gpt-5-mini"),
    add_history_to_context=True,  # The member will have access to it's own history. No need to set a DB on the member.
)

spanish_agent = Agent(
    name="Spanish Agent",
    role="You answer Spanish questions.",
    model=OpenAIChat(id="gpt-5-mini"),
    add_history_to_context=True,  # The member will have access to it's own history. No need to set a DB on the member.
)


multi_lingual_q_and_a_team = Team(
    name="Multi Lingual Q and A Team",
    model=OpenAIChat("gpt-5-mini"),
    members=[german_agent, spanish_agent],
    instructions=[
        "You are a multi lingual Q and A team that can answer questions in English and Spanish. You MUST delegate the task to the appropriate member based on the language of the question.",
        "If the question is in German, delegate to the German agent. If the question is in Spanish, delegate to the Spanish agent.",
    ],
    db=SqliteDb(
        db_file="tmp/multi_lingual_q_and_a_team.db"
    ),  # Add a database to store the conversation history. This is a requirement for history to work correctly.
    determine_input_for_members=False,  # Send the input directly to the member agents without the team leader synthesizing its own input.
    respond_directly=True,  # The team leader will not process responses from the members and instead will return them directly.
)


session_id = f"conversation_{uuid4()}"

## Ask question in German
multi_lingual_q_and_a_team.print_response(
    "Hallo, wie heißt du? Mein Name ist John.", stream=True, session_id=session_id
)

## Follow up in German
multi_lingual_q_and_a_team.print_response(
    "Erzähl mir eine Geschichte mit zwei Sätzen und verwende dabei meinen richtigen Namen.",
    stream=True,
    session_id=session_id,
)

## Ask question in Spanish
multi_lingual_q_and_a_team.print_response(
    "Hola, ¿cómo se llama? Mi nombre es Juan.", stream=True, session_id=session_id
)

## Follow up in Spanish
multi_lingual_q_and_a_team.print_response(
    "Cuenta una historia de dos oraciones y utiliza mi nombre real.",
    stream=True,
    session_id=session_id,
)
