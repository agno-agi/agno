"""
Simple example demonstrating store_history_messages option
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.utils.pprint import pprint_run_response

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=SqliteDb(db_file="tmp/example_no_history.db"),
    add_history_to_context=True,  # Use history during execution
    num_history_runs=3,
    store_history_messages=False,  # Don't store history messages in database
)

if __name__ == "__main__":
    print("\n=== First Run: Establishing context ===")
    response1 = agent.run("My name is Alice and I love Python programming.")
    pprint_run_response(response1)

    print("\n=== Second Run: Using history (but not storing it) ===")
    response2 = agent.run("What is my name and what do I love?")
    pprint_run_response(response2)

    # Check what was stored
    stored_run = agent.get_last_run_output()
    if stored_run and stored_run.messages:
        history_messages = [m for m in stored_run.messages if m.from_history]
        print("\n Storage Info:")
        print(f"   Total messages stored: {len(stored_run.messages)}")
        print(f"   History messages: {len(history_messages)} (scrubbed!)")
        print("\n History was used during execution (agent knew the answer)")
        print("   but history messages are NOT stored in the database!")
