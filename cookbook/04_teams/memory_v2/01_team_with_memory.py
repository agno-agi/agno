from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from rich.pretty import pprint

db = SqliteDb(db_file="tmp/team_memory_v2.db")

user_id = "john_doe@example.com"

# Create a member agent
agent = Agent(
    name="Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
)

# Create team with memory v2 enabled
team = Team(
    name="Memory Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[agent],
    db=db,
    enable_agentic_memory_v2=True,
    markdown=True,
)

# First interaction: share information
team.print_response(
    "My name is John Doe. I work at Acme Corp as a software engineer. "
    "I love hiking and playing chess.",
    stream=True,
    user_id=user_id,
)

# Second interaction: ask a question
team.print_response(
    "What do you know about me?",
    stream=True,
    user_id=user_id,
)

# Third interaction: ask a question
team.print_response(
    "I do not like long responses. Can you be more concise? Also I hate hiking",
    stream=True,
    user_id=user_id,
)


# View the stored profile
print("\n--- User Profile ---")
profile = team.get_user_profile(user_id)
if profile:
    pprint(profile.to_dict())
