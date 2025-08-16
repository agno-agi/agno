from agno.agent.agent import Agent
from agno.db.redis import RedisDb
from agno.models.openai import OpenAIChat

# Set up Redis database
db_url = "redis://localhost:6379"
db = RedisDb(db_url=db_url)

session_id = "redis_memories"
user_id = "redis_user"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Pass the database to the agent
    db=db,
    # Enable memory
    enable_user_memories=True,
    enable_session_summaries=True,
)

agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=user_id,
    session_id=session_id,
)

agent.print_response(
    "What are my hobbies?", stream=True, user_id=user_id, session_id=session_id
)
