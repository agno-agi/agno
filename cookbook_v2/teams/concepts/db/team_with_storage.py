"""
This example demonstrates how to create a multi-language team with persistent storage.

The team uses PostgresDb for storing session data and can route questions to
appropriate language-specific agents based on the input language.
"""

from uuid import uuid4

from agno.agent.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.models.mistral import MistralChat
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# Database configuration
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="agent_team_sessions")

# Create language-specific agents
french_agent = Agent(
    name="French Agent",
    role="You can only answer in French",
    model=MistralChat(id="mistral-large-latest"),
    instructions=[
        "You must only respond in French",
    ],
)

english_agent = Agent(
    name="English Agent", 
    role="You can only answer in English",
    model=OpenAIChat("gpt-4o"),
    instructions=[
        "You must only respond in English",
    ],
)

# Generate unique IDs
user_id = str(uuid4())
team_id = str(uuid4())

# Create the multi-language team with storage
multi_language_team = Team(
    name="Multi Language Team",
    mode="route",
    team_id=team_id,
    model=OpenAIChat("gpt-4o"),
    members=[
        french_agent,
        english_agent,
    ],
    db=db,
    enable_user_memories=True,
    markdown=True,
    instructions=[
        "You are a language router that directs questions to the appropriate language agent.",
        "If the user asks in a language whose agent is not a team member, respond in English with:",
        "'I can only answer in the following languages: English, Spanish, Japanese, French and German. Please ask your question in one of these languages.'",
        "Always check the language of the user's input before routing to an agent.",
        "For unsupported languages like Italian, respond in English with the above message.",
    ],
    show_members_responses=True,
    add_history_to_context=True,
    num_history_runs=3,
)

# Test the team with French input
multi_language_team.print_response(
    "Comment allez-vous?",
    stream=True,
    user_id=user_id,
)

# Test context memory with follow-up question
multi_language_team.print_response(
    "Qu'est-ce que je viens de dire?",
    stream=True,
    user_id=user_id,
)
