"""Customer Support - A realistic frustrated customer journey.

This example shows a single customer with a complex sync issue.
The conversation evolves from confusion to frustration to resolution.
Uses AUTOMATIC memory extraction (no explicit tools).
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.memory_v2 import MemoryCompiler
from agno.models.openai import OpenAIChat

db = SqliteDb(db_file="tmp/support_memory.db")
memory = MemoryCompiler(model=OpenAIChat(id="gpt-4o-mini"))

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    memory_compiler=memory,
    update_memory_on_run=True,
    instructions=(
        "You are a customer support agent for CloudSync, a file synchronization "
        "SaaS product. Be helpful, empathetic, and professional."
    ),
    markdown=True,
)

USER_ID = "marcus_techflow"


def show_profile():
    user = memory.get_user_profile(USER_ID)
    if not user:
        return

    if user.user_profile:
        print("\n[CUSTOMER]")
        for k, v in user.user_profile.items():
            print(f"  {k}: {v}")

    policies = user.memory_layers.get("policies", {})
    if policies:
        print("\n[PREFERENCES]")
        for k, v in policies.items():
            print(f"  {k}: {v}")

    knowledge = user.memory_layers.get("knowledge", [])
    if knowledge:
        print("\n[CONTEXT]")
        for item in knowledge:
            if isinstance(item, dict):
                print(f"  {item.get('key', '?')}: {item.get('value', item)}")


def chat(message: str):
    agent.print_response(message, user_id=USER_ID, stream=True)


# Initial contact
chat("hi my files arent syncing. getting some kind of error")
chat("it says SYNC_TIMEOUT_504. what does that even mean")
chat(
    "im on the business plan i think? my company is TechFlow Inc. im the IT manager here"
)

show_profile()

# Troubleshooting
chat("yeah i tried restarting the app. still broken")
chat("the files that fail are around 80-100MB each. theyre video files")
chat("we upload maybe 30-40 files a day. mostly in the morning")
chat("ok i tried that chunked upload setting. still failing on bigger files")

# Frustration
chat("look this is really frustrating. weve been customers for 2 years")
chat("can you escalate this? i need to talk to an actual engineer")

show_profile()

# Resolution
chat("[next day] the engineer's fix worked! smaller chunk sizes solved everything")
chat("thanks for escalating quickly. thats refreshing for support")
chat("can you explain WHY this was happening? i need to document it")
chat("perfect. large files hitting the timeout threshold. got it")
chat("ill definitely recommend CloudSync. you guys handled this well")

show_profile()
