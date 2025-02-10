"""
This recipe shows how to store personalized memories and summaries in a sqlite database.
Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/memory/03_memories_and_summaries.py` to run the agent
"""

import json

from agno.agent import Agent, AgentMemory
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # The memories are personalized for this user
    user_id="john_billings",
    # Store the memories and summary in a table: agent_memory
    memory=AgentMemory(
        db=SqliteMemoryDb(
            table_name="agent_memory",
            db_file="tmp/agent_memory.db",
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
    # Store agent sessions in a database, that persists between runs
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/agent_storage.db"
    ),
    # add_history_to_messages=true adds the chat history to the messages sent to the Model.
    add_history_to_messages=True,
    # Number of historical responses to add to the messages.
    num_history_responses=3,
    # Description creates a system prompt for the agent
    description="You are a helpful assistant that always responds in a polite, upbeat and positive manner.",
)

console = Console()


def render_panel(title: str, content: str) -> Panel:
    return Panel(JSON(content, indent=4), title=title, expand=True)


def print_agent_memory(agent):
    # -*- Print history
    console.print(
        render_panel(
            f"Chat History for session_id: {agent.session_id}",
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
            f"Memories for user_id: {agent.user_id}",
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
        render_panel(
            f"Summary for session_id: {agent.session_id}",
            json.dumps(agent.memory.summary.model_dump(), indent=4),
        )
    )


# -*- Share personal information
agent.print_response("My name is john billings and I live in nyc.", stream=True)
# -*- Print agent memory
print_agent_memory(agent)

# -*- Share personal information
agent.print_response("I'm going to a concert tomorrow?", stream=True)
# -*- Print agent memory
print_agent_memory(agent)

# Ask about the conversation
agent.print_response(
    "What have we been talking about, do you know my name?", stream=True
)
