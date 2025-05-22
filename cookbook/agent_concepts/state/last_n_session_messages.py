from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage

agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    # Fix the session id to continue the same session across execution cycles
    session_id="fixed_id_for_demo_2",
    user_id="user_1",
    storage=SqliteStorage(table_name="agent_sessions_new", db_file="tmp/data.db"),
    add_history_to_messages=True,
    num_history_runs=3,
    search_previous_sessions_history=True,
    num_history_sessions=3,
    show_tool_calls=True,
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
agent.print_response("What did I discuss in my previous conversations?", session_id=session_5_id)  # It should only include the last 3 sessions


