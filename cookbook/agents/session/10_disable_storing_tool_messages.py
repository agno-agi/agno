"""
Simple examples demonstrating store_tool_messages option
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.hackernews import HackerNewsTools
from agno.utils.pprint import pprint_run_response

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    db=SqliteDb(db_file="tmp/example_no_tools.db"),
    store_tool_messages=False,  # Don't store tool execution details
)

if __name__ == "__main__":
    print("\nRunning agent with tools but NOT storing tool results...")
    response = agent.run("What is the latest news from Hacker News?")

    pprint_run_response(response)

    # Check what was stored
    stored_run = agent.get_last_run_output()
    if stored_run and stored_run.messages:
        tool_messages = [m for m in stored_run.messages if m.role == "tool"]
        print("\n Storage info:")
        print(f"   Total messages stored: {len(stored_run.messages)}")
        print(f"   Tool result messages: {len(tool_messages)} (scrubbed!)")
