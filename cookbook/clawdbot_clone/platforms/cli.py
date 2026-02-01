"""
CLI Platform for Clawdbot Clone.

Interactive command-line interface for testing and local use.
"""

import asyncio
from typing import Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from ..agent import create_clawdbot
from ..config import ClawdbotConfig, get_config

console = Console()


def run_cli(config: Optional[ClawdbotConfig] = None, user_id: str = "cli_user") -> None:
    """
    Run the Clawdbot in an interactive CLI session.

    Args:
        config: Configuration object. If None, loads from environment.
        user_id: User ID for memory isolation.
    """
    if config is None:
        config = get_config()

    agent = create_clawdbot(config)
    session_id = "cli_session"

    console.print(
        Panel(
            f"[bold green]{config.bot_name}[/bold green] - Your Personal AI Assistant\n\n"
            "Type your message and press Enter. Type 'quit' or 'exit' to stop.\n"
            "Type 'memories' to see what I remember about you.\n"
            "Type 'clear' to start a new session.",
            title="Welcome",
            border_style="green",
        )
    )

    while True:
        try:
            user_input = console.input("\n[bold blue]You:[/bold blue] ").strip()

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "bye"):
                console.print(f"\n[dim]{config.bot_name}: Goodbye! Talk to you later.[/dim]")
                break

            if user_input.lower() == "memories":
                memories = agent.get_user_memories(user_id=user_id)
                if memories:
                    console.print("\n[bold]Your Memories:[/bold]")
                    for i, m in enumerate(memories, 1):
                        console.print(f"  {i}. {m.memory}")
                else:
                    console.print("[dim]No memories stored yet.[/dim]")
                continue

            if user_input.lower() == "clear":
                session_id = f"cli_session_{asyncio.get_event_loop().time()}"
                console.print("[dim]Session cleared. Starting fresh conversation.[/dim]")
                continue

            # Get response from agent
            console.print(f"\n[bold green]{config.bot_name}:[/bold green]")

            response = agent.run(
                input=user_input,
                user_id=user_id,
                session_id=session_id,
            )

            if response.content:
                # Render as markdown for nice formatting
                md = Markdown(str(response.content))
                console.print(md)

        except KeyboardInterrupt:
            console.print(f"\n\n[dim]{config.bot_name}: Interrupted. Goodbye![/dim]")
            break
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")


async def run_cli_async(config: Optional[ClawdbotConfig] = None, user_id: str = "cli_user") -> None:
    """
    Async version of the CLI runner.

    Args:
        config: Configuration object.
        user_id: User ID for memory isolation.
    """
    if config is None:
        config = get_config()

    agent = create_clawdbot(config)
    session_id = "cli_session"

    console.print(
        Panel(
            f"[bold green]{config.bot_name}[/bold green] - Your Personal AI Assistant (Async Mode)\n\n"
            "Type your message and press Enter. Type 'quit' or 'exit' to stop.",
            title="Welcome",
            border_style="green",
        )
    )

    while True:
        try:
            # Use asyncio for non-blocking input
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: console.input("\n[bold blue]You:[/bold blue] ").strip()
            )

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit", "bye"):
                console.print(f"\n[dim]{config.bot_name}: Goodbye![/dim]")
                break

            console.print(f"\n[bold green]{config.bot_name}:[/bold green]")

            response = await agent.arun(
                input=user_input,
                user_id=user_id,
                session_id=session_id,
            )

            if response.content:
                md = Markdown(str(response.content))
                console.print(md)

        except KeyboardInterrupt:
            console.print(f"\n\n[dim]{config.bot_name}: Interrupted. Goodbye![/dim]")
            break


if __name__ == "__main__":
    run_cli()
