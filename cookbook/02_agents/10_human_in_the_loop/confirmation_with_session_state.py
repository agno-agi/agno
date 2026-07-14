"""
Confirmation with Session State
=============================

HITL confirmation where the tool modifies session_state before pausing.
Verifies that state changes survive the pause/continue round-trip.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.run import RunContext, RunStatus
from agno.tools import tool
from agno.utils import pprint
from rich.console import Console
from rich.prompt import Prompt

console = Console()


@tool(requires_confirmation=True)
def add_to_watchlist(run_context: RunContext, symbol: str) -> str:
    """Add a stock symbol to the user's watchlist. Requires confirmation.

    Args:
        symbol: Stock ticker symbol (e.g. AAPL, TSLA)

    Returns:
        Confirmation message with updated watchlist
    """
    if run_context.session_state is None:
        run_context.session_state = {}

    watchlist = run_context.session_state.get("watchlist", [])
    symbol = symbol.upper()
    if symbol not in watchlist:
        watchlist.append(symbol)
    run_context.session_state["watchlist"] = watchlist
    return f"Added {symbol} to watchlist. Current watchlist: {watchlist}"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[add_to_watchlist],
    session_state={"watchlist": []},
    instructions="You MUST use the add_to_watchlist tool when the user asks to add a stock. The user's watchlist is: {watchlist}",
    db=SqliteDb(db_file="tmp/hitl_state.db"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console.print(
        "[bold]Step 1:[/] Asking agent to add AAPL to watchlist (will pause for confirmation)"
    )
    run_response = agent.run("Add AAPL to my watchlist using the add_to_watchlist tool")

    console.print(f"[dim]Status: {run_response.status}[/]")
    console.print(f"[dim]Session state after pause: {agent.get_session_state()}[/]")

    if run_response.status != RunStatus.paused:
        console.print(
            "[yellow]Agent did not pause (model may not have called the tool). Try re-running.[/]"
        )
    else:
        for requirement in run_response.active_requirements:
            if requirement.needs_confirmation:
                console.print(
                    f"Tool [bold blue]{requirement.tool_execution.tool_name}({requirement.tool_execution.tool_args})[/] requires confirmation."
                )
                message = (
                    Prompt.ask(
                        "Do you want to continue?", choices=["y", "n"], default="y"
                    )
                    .strip()
                    .lower()
                )
                if message == "n":
                    requirement.reject()
                else:
                    requirement.confirm()

        console.print("\n[bold]Step 2:[/] Continuing run after confirmation")
        run_response = agent.continue_run(
            run_id=run_response.run_id,
            requirements=run_response.requirements,
        )

        pprint.pprint_run_response(run_response)

        final_state = agent.get_session_state()
        console.print(f"\n[bold green]Final session state:[/] {final_state}")
