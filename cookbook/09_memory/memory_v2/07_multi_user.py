import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

DB_FILE = "tmp/multi_user_memory.db"

USER_1 = "mark@example.com"
USER_2 = "john@example.com"
USER_3 = "jane@example.com"

db = SqliteDb(db_file=DB_FILE)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    update_memory_on_run=True,
    markdown=True,
)


async def run_conversations():
    # User 1: Mark - anime and gaming enthusiast
    await agent.aprint_response(
        "My name is Mark Gonzales and I like anime and video games.",
        user_id=USER_1,
    )
    await agent.aprint_response(
        "I also enjoy reading manga and playing RPGs.",
        user_id=USER_1,
    )

    # User 2: John - outdoor enthusiast
    await agent.aprint_response(
        "Hi my name is John Doe.",
        user_id=USER_2,
    )
    await agent.aprint_response(
        "I'm planning to hike this weekend. I love mountain trails.",
        user_id=USER_2,
    )

    # User 3: Jane - fitness enthusiast
    await agent.aprint_response(
        "Hi my name is Jane Smith.",
        user_id=USER_3,
    )
    await agent.aprint_response(
        "I'm going to the gym tomorrow. I do CrossFit.",
        user_id=USER_3,
    )

    # Ask for personalized recommendations - agent uses each user's memory
    await agent.aprint_response(
        "What do you suggest I do this weekend?",
        user_id=USER_1,
    )


if __name__ == "__main__":
    asyncio.run(run_conversations())

    print("\n" + "=" * 60)
    print("USER PROFILES")
    print("=" * 60)

    print("\nMark's profile:")
    user_1 = agent.get_user_memory_v2(USER_1)
    if user_1:
        pprint(user_1.to_dict())

    print("\nJohn's profile:")
    user_2 = agent.get_user_memory_v2(USER_2)
    if user_2:
        pprint(user_2.to_dict())

    print("\nJane's profile:")
    user_3 = agent.get_user_memory_v2(USER_3)
    if user_3:
        pprint(user_3.to_dict())
