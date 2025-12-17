from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team import Team

db = SqliteDb(db_file="tmp/teams.db", session_table="team_sessions")

INTRODUCTION = """Hello, I'm your personal assistant. I can help you only with questions related to mountain climbing."""

agent = Agent(
    model=OpenAIChat(),
)

team = Team(
    model=OpenAIChat(),
    db=db,
    members=[agent],
    introduction=INTRODUCTION,
    session_id="introduction_session_mountain_climbing",
    add_history_to_context=True,
)
team.print_response("Easiest 14er in USA?")
team.print_response("Is K2 harder to climb than Everest?")
