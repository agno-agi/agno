"""
This recipe shows how to use personalized memories and summaries in an agent.
Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/agents/memories_and_summaries_sqlite.py` to run the agent
"""

import asyncio
import json

from agno.agent import Agent, AgentMemory
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

agent_memory_file: str = "tmp/agent_memory.db"
agent_storage_file: str = "tmp/agent_storage.db"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # The memories are personalized for this user
    user_id="john_billings",
    # Store the memories and summary in a table: agent_memory
    memory=AgentMemory(
        db=SqliteMemoryDb(
            table_name="agent_memory",
            db_file=agent_memory_file,
        ),
        # Create and store personalized memories for this user
        create_user_memories=True,
        # Update memories for the user after each run
        update_user_memories_after_run=True,
        # Create and store session summaries
        create_session_summary=True,
        # Update session summaries after each run
        update_session_summary_after_run=True,
    ),
    # Store agent sessions in a database
    storage=SqliteAgentStorage(table_name="agent_sessions", db_file=agent_storage_file),
    description="You are a helpful assistant that always responds in a polite, upbeat and positive manner.",
    # Show debug logs to see the memory being created
    # debug_mode=True,
)

console = Console()


def render_panel(title: str, content: str) -> Panel:
    return Panel(JSON(content, indent=4), title=title, expand=True)


def print_agent_memory(agent):
    # -*- Print history
    console.print(
        render_panel(
            "Chat History",
            json.dumps(
                [
                    m.model_dump(include={"role", "content"})
                    for m in agent.memory.messages
                ],
                indent=4,
            ),
        )
    )
    # -*- Print memories
    console.print(
        render_panel(
            "Memories",
            json.dumps(
                [
                    m.model_dump(include={"memory", "input"})
                    for m in agent.memory.memories
                ],
                indent=4,
            ),
        )
    )
    # -*- Print summary
    console.print(
        render_panel("Summary", json.dumps(agent.memory.summary.model_dump(), indent=4))
    )


async def main():
    # -*- Share personal information
    await agent.aprint_response("My name is john billings?", stream=True)
    # -*- Print agent memory
    print_agent_memory(agent)

    # -*- Share personal information
    await agent.aprint_response("I live in nyc?", stream=True)
    # -*- Print agent memory
    print_agent_memory(agent)

    # -*- Share personal information
    await agent.aprint_response("I'm going to a concert tomorrow?", stream=True)
    # -*- Print agent memory
    print_agent_memory(agent)

    # Ask about the conversation
    await agent.aprint_response(
        "What have we been talking about, do you know my name?", stream=True
    )


# Run the async main function
if __name__ == "__main__":
    asyncio.run(main())
