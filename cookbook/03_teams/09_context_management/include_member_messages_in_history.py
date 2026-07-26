"""
Include Member Messages In History
==================================

Leader follow-ups can include stored member run messages when building history.
Requires store_member_responses=True and include_member_messages_in_history=True.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

team = Team(
    model=OpenAIResponses(id="gpt-5.2"),
    members=[
        Agent(model=OpenAIResponses(id="gpt-5.2"), name="SQL Agent", role="Runs SQL")
    ],
    db=SqliteDb(db_file="tmp/member_history_team.db"),
    add_history_to_context=True,
    store_member_responses=True,
    include_member_messages_in_history=True,
)

if __name__ == "__main__":
    team.print_response(
        "Ask the SQL agent to summarize table counts.", session_id="member_history_demo"
    )
    team.print_response(
        "What did the member agent do in the last run?",
        session_id="member_history_demo",
    )
