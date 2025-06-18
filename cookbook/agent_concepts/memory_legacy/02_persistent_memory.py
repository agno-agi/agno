"""
This recipe shows how to store agent sessions in a sqlite database.
Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/memory/02_persistent_memory.py` to run the agent
"""

import json

from agno.agent import Agent
from agno.memory import AgentMemory
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory=AgentMemory(),
    # Store agent sessions in a database
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/agent_storage.db"
    ),
    # Set add_history_to_messages=true to add the previous chat history to the messages sent to the Model.
    add_history_to_messages=True,
    # Number of historical responses to add to the messages.
    num_history_responses=3,
    # The session_id is used to identify the session in the database
    # You can resume any session by providing a session_id
    # session_id="xxxx-xxxx-xxxx-xxxx",
    # Description creates a system prompt for the agent
    description="You are a helpful assistant that always responds in a polite, upbeat and positive manner.",
)

console = Console()


def print_chat_history(agent):
    # -*- Print history
    console.print(
        Panel(
            JSON(
                json.dumps(
                    [
                        m.model_dump(include={"role", "content"})
                        for m in agent.memory.messages
                    ]
                ),
                indent=4,
            ),
            title=f"Chat History for session_id: {agent.session_id}",
            expand=True,
        )
    )


# -*- Create a run
agent.print_response("Share a 2 sentence horror story", stream=True)
# -*- Print the chat history
print_chat_history(agent)

# -*- Ask a follow up question that continues the conversation
agent.print_response("What was my first message?", stream=True)
# -*- Print the chat history
print_chat_history(agent)
