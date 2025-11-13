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
from typing import List, Optional

import typer
from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.session import AgentSession
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.prompt import Prompt


def create_agent(user: str = "user"):
    session_id: Optional[str] = None

    # Ask if user wants to start new session or continue existing one
    new = typer.confirm("Do you want to start a new session?")

    # Initialize storage for both agent sessions and memories
    db = SqliteDb(db_file="tmp/agents.db")

    if not new:
        existing_sessions: List[AgentSession] = db.get_sessions(
            user_id=user, session_type=SessionType.AGENT
        )  # type: ignore
        if len(existing_sessions) > 0:
            session_id = existing_sessions[0].session_id

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        user_id=user,
        session_id=session_id,
        enable_user_memories=True,
        enable_session_summaries=True,
        db=db,
        add_history_to_context=True,
        num_history_runs=3,
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
    messages = agent.get_session_messages()
    console.print(
        Panel(
            JSON(
                json.dumps(
                    [m.model_dump(include={"role", "content"}) for m in messages],
                    indent=4,
                ),
            ),
            title=f"Chat History for session_id: {agent.session_id}",
            expand=True,
        )
    )

    # Print user memories
    user_memories = agent.get_user_memories(user_id=agent.user_id)
    if user_memories:
        memories_data = [memory.to_dict() for memory in user_memories]
        console.print(
            Panel(
                JSON(json.dumps(memories_data, indent=4)),
                title=f"Memories for user_id: {agent.user_id}",
                expand=True,
            )
        )

    # Print session summaries
    try:
        session_summary = agent.get_session_summary()
        if session_summary:
            console.print(
                Panel(
                    JSON(
                        json.dumps(session_summary.to_dict(), indent=4),
                    ),
                    title=f"Session Summary for session_id: {agent.session_id}",
                    expand=True,
                )
            )
        else:
            console.print(
                "Session summary: Not yet created (summaries are created after multiple interactions)"
            )
    except Exception as e:
        console.print(f"Session summary error: {e}")


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

        agent.print_response(input=message, stream=True, markdown=True)
        print_agent_memory(agent)


if __name__ == "__main__":
    typer.run(main)
