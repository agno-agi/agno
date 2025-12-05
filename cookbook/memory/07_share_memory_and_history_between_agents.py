from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai.chat import OpenAIChat

db = SqliteDb(db_file="tmp/agent_sessions.db")

session_id = str(uuid4())
user_id = "john_doe@example.com"

agent_1 = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are really friendly and helpful.",
    db=db,
    add_history_to_context=True,
    enable_user_memories=True,
)

agent_2 = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are really grumpy and mean.",
    db=db,
    add_history_to_context=True,
    enable_user_memories=True,
)

agent_1.print_response(
    "Hi! My name is John Doe.", session_id=session_id, user_id=user_id
)

agent_2.print_response("What is my name?", session_id=session_id, user_id=user_id)

agent_2.print_response(
    "I like to hike in the mountains on weekends.",
    session_id=session_id,
    user_id=user_id,
)

agent_1.print_response("What are my hobbies?", session_id=session_id, user_id=user_id)

agent_1.print_response(
    "What have we been discussing? Give me bullet points.",
    session_id=session_id,
    user_id=user_id,
)
