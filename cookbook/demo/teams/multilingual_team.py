from textwrap import dedent

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# ************* Database Setup *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, id="agno_assist_db")
# *******************************


# ************* Description and Instructions *************
description = dedent(
    """\
    You are a team of agents that can answer questions in multiple languages.
    """
)

instructions = dedent(
    """\
    Help the user with their question in the language they prefer.
    If the user asks in a language that is not supported, let them know that you only answer in the following languages: Japanese, Spanish, French, Hindi and German.
    Based on the language of the user's question, route the question to the appropriate agent.
    Always check the language of the user's input before routing to an agent.
    Only respond directly if the user asks a question in English. For other languages, you must delegate the task to the appropriate agent.
    """
)
# *******************************

# ************* Agents *************
japanese_agent = Agent(
    name="Japanese Agent",
    role="You only answer in Japanese",
    model=OpenAIChat(id="gpt-5-nano "),
)
spanish_agent = Agent(
    name="Spanish Agent",
    role="You only answer in Spanish",
    model=OpenAIChat(id="gpt-5-nano"),
)
french_agent = Agent(
    name="French Agent",
    role="You only answer in French",
    model=OpenAIChat(id="gpt-5-nano"),
)
hindi_agent = Agent(
    name="Hindi Agent",
    role="You only answer in Hindi",
    model=OpenAIChat(id="gpt-5-nano"),
)
german_agent = Agent(
    name="German Agent",
    role="You only answer in German",
    model=OpenAIChat(id="gpt-5-nano"),
)
# *******************************

# ************* Team *************
multilingual_team = Team(
    name="Multilingual Team",
    model=OpenAIChat(id="gpt-5-mini"),
    description=description,
    instructions=instructions,
    members=[japanese_agent, spanish_agent, french_agent, hindi_agent, german_agent],
    respond_directly=True,
    add_history_to_context=True,
)
# *******************************
