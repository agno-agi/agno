import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

# Remove the tmp db file before running the script
os.remove("tmp/data.db")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    user_id="user_1",
    db=SqliteDb(db_file="tmp/data.db"),
    add_history_to_context=True,
    num_history_runs=3,
    search_session_history=True,  # allow searching previous sessions
    num_history_sessions=2,  # only include the last 2 sessions in the search to avoid context length issues
)

session_1_id = "session_1_id"
session_2_id = "session_2_id"
session_3_id = "session_3_id"
session_4_id = "session_4_id"
session_5_id = "session_5_id"

agent.print_response("What is the capital of South Africa?", session_id=session_1_id)
agent.print_response("What is the capital of China?", session_id=session_2_id)
agent.print_response("What is the capital of France?", session_id=session_3_id)
agent.print_response("What is the capital of Japan?", session_id=session_4_id)
agent.print_response(
    "What did I discuss in my previous conversations?", session_id=session_5_id
)  # It should only include the last 2 sessions
