from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
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
    number_of_sessions=3,
    show_tool_calls=True,
)

agent.print_response("What was my last question?")
agent.print_response("What is the capital of South America?")
agent.print_response("What was my last conversation?")
