"""Basic Memory V2 - Agent learns user information via agentic memory tools.

Demonstrates:
- enable_agentic_memory_v2: Agent gets save/delete tools to manage user memory
- Agent extracts profile info (name, role, company)
- Agent saves user policies (be concise, include code examples)
- Agent can forget information on request
"""

import json

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich import print_json

DB_FILE = "tmp/user_memory.db"
USER_ID = "sarah"

db = SqliteDb(db_file=DB_FILE)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    enable_agentic_memory_v2=True,
    markdown=True,
    user_id=USER_ID,
)

agent.print_response(
    "Hi, I'm Sarah, a backend engineer at TechCorp. I work with Python and Go.",
)

agent.print_response(
    "Please be concise and always include code examples when explaining things.",
)

agent.print_response(
    "Forget my workplace details.",
)

agent.print_response(
    "I'm currently building a REST API for our payment service using FastAPI.",
)

agent.print_response(
    "What's a good way to structure API endpoints?",
)

agent.print_response(
    "What do you know about me and my work?",
)

agent.print_response(
    "I don't like a lot of code. Focus on explaining to me the concept in detail without code examples.",
)

print("\n" + "=" * 60)
print("SARAH'S MEMORY PROFILE")
print("=" * 60)

user = agent.get_user_memory_v2(USER_ID)
if user:
    print_json(json.dumps(user.to_dict()))
else:
    print("No user memory found")
