"""🧠 Long Term User Memories and Session Summaries

This example shows how to create an agent with persistent memory that stores:
1. Personalized user memories - facts and preferences learned about specific users
2. Session summaries - key points and context from conversations
3. Chat history - stored in SQLite for persistence

Key features:
- Stores user-specific memories in SQLite database
- Maintains session summaries for context
- Continues conversations across sessions with memory
- References previous context and user information in responses

Examples:
User: "My name is John and I live in NYC"
Agent: *Creates memory about John's location*

User: "What do you remember about me?"
Agent: *Recalls previous memories about John*

Run: `pip install openai sqlalchemy agno` to install dependencies
"""

import json
from textwrap import dedent
from typing import Optional

import typer
from agno.agent import Agent, AgentMemory
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.prompt import Prompt


def create_agent(user: str = "user"):
    session_id: Optional[str] = None

    # Ask if user wants to start new session or continue existing one
    new = typer.confirm("Do you want to start a new session?")

    # Initialize storage for both agent sessions and memories
    agent_storage = SqliteStorage(table_name="agent_memories", db_file="tmp/agents.db")

    if not new:
        existing_sessions = agent_storage.get_all_session_ids(user)
        if len(existing_sessions) > 0:
            session_id = existing_sessions[0]

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        user_id=user,
        session_id=session_id,
        # Configure memory system with SQLite storage
        memory=AgentMemory(
            db=SqliteMemoryDb(
                table_name="agent_memory",
                db_file="tmp/agent_memory.db",
            ),
            create_user_memories=True,
            update_user_memories_after_run=True,
            create_session_summary=True,
            update_session_summary_after_run=True,
        ),
        storage=agent_storage,
        add_history_to_messages=True,
        num_history_responses=3,
        # Enhanced system prompt for better personality and memory usage
        description=dedent("""\
        You are a helpful and friendly AI assistant with excellent memory.
        - Remember important details about users and reference them naturally
        - Maintain a warm, positive tone while being precise and helpful
        - When appropriate, refer back to previous conversations and memories
        - Always be truthful about what you remember or don't remember"""),
    )

    if session_id is None:
        session_id = agent.session_id
        if session_id is not None:
            print(f"Started Session: {session_id}\n")
        else:
            print("Started Session\n")
    else:
        print(f"Continuing Session: {session_id}\n")

    return agent


def print_agent_memory(agent):
    """Print the current state of agent's memory systems"""
    console = Console()

    # Print chat history
    console.print(
        Panel(
            JSON(
                json.dumps([m.to_dict() for m in agent.memory.messages]),
                indent=4,
            ),
            title=f"Chat History for session_id: {agent.session_id}",
            expand=True,
        )
    )

    # Print user memories
    console.print(
        Panel(
            JSON(
                json.dumps(
                    [
                        m.model_dump(include={"memory", "input"})
                        for m in agent.memory.memories
                    ]
                ),
                indent=4,
            ),
            title=f"Memories for user_id: {agent.user_id}",
            expand=True,
        )
    )

    # Print session summary
    console.print(
        Panel(
            JSON(json.dumps(agent.memory.summary.model_dump(), indent=4)),
            title=f"Summary for session_id: {agent.session_id}",
            expand=True,
        )
    )


def main(user: str = "user"):
    """Interactive chat loop with memory display"""
    agent = create_agent(user)

    print("Try these example inputs:")
    print("- 'My name is [name] and I live in [city]'")
    print("- 'I love [hobby/interest]'")
    print("- 'What do you remember about me?'")
    print("- 'What have we discussed so far?'\n")

    exit_on = ["exit", "quit", "bye"]
    while True:
        message = Prompt.ask(f"[bold] :sunglasses: {user} [/bold]")
        if message in exit_on:
            break

        agent.print_response(message=message, stream=True, markdown=True)
        print_agent_memory(agent)


if __name__ == "__main__":
    typer.run(main)
