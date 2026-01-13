from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from rich.pretty import pprint

# Database connection
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(
    db_url=db_url,
    session_table="sessions",
    memory_table="user_memories",
)

user_id = "peter_rabbit"

# Create agent with the new memory system
agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    user_id=user_id,
    db=db,
    # Enable the Agent to dynamically create and manage user memories
    enable_user_memories=True,
    add_datetime_to_context=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response("My name is Peter Rabbit and I like to eat carrots.")

    # Get memories using the agent's method
    memories = agent.get_user_memories(user_id=user_id)
    print(f"Memories about {user_id}:")
    pprint(memories)

    agent.print_response("What is my favorite food?")
    agent.print_response("My best friend is Jemima Puddleduck.")

    # Get updated memories
    memories = agent.get_user_memories(user_id=user_id)
    print(f"Memories about {user_id}:")
    pprint(memories)

    agent.print_response("Recommend a good lunch meal, who should i invite?")
    agent.print_response("What have we been talking about?")
