"""
Human in the Loop - Approve Before the Agent Acts
==================================================
This example pauses an agent before it executes a tool that has an external
effect. The user can inspect the exact tool call, approve it, or reject it.

The demo uses a simulated publishing tool, so it does not contact an external
service. The confirmation pattern is the same for email, payments, database
writes, deployments, or any other sensitive action.

Key concepts:
- @tool(requires_confirmation=True): Mark an action that needs approval
- active_requirements: Inspect what the run is waiting for
- confirm() / reject(): Record the user's decision
- continue_run(): Resume the same run after the decision

Example prompts to try:
- "Research NVDA and publish a three-bullet brief"
- "Draft an AMD comparison, but ask before publishing it"
- "Prepare a Tesla brief and do not publish it"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.tools import tool
from agno.tools.yfinance import YFinanceTools
from agno.utils import pprint
from rich.console import Console
from rich.prompt import Prompt

# ---------------------------------------------------------------------------
# Storage Configuration
# ---------------------------------------------------------------------------
hitl_db = SqliteDb(
    id="quickstart-human-in-the-loop-db",
    db_file="tmp/quickstart/human_in_the_loop.db",
)


# ---------------------------------------------------------------------------
# Sensitive Tool
# ---------------------------------------------------------------------------
@tool(requires_confirmation=True)
def publish_research_brief(title: str, summary: str) -> str:
    """
    Publish a research brief.

    This quickstart simulates publishing and does not call an external service.

    Args:
        title: Public title for the brief
        summary: Final brief to publish

    Returns:
        Confirmation that the simulated publish completed
    """
    return f"Published '{title}' ({len(summary)} characters)"


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a market research partner.

1. Use Yahoo Finance to gather current facts.
2. Produce a concise, evidence-based brief.
3. Only call publish_research_brief when the user explicitly asks to publish.
4. Never claim publication succeeded until the tool has executed.
5. Treat the publishing tool as a simulated external action in this demo.\
"""

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
human_in_the_loop_agent = Agent(
    name="Agent with Human in the Loop",
    model=Gemini(id="gemini-3.6-flash"),
    instructions=instructions,
    tools=[
        YFinanceTools(
            enable_company_info=True,
            enable_stock_fundamentals=True,
            enable_company_news=True,
        ),
        publish_research_brief,
    ],
    db=hitl_db,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    console = Console()
    session_id = "human-in-the-loop-session"
    run_response = human_in_the_loop_agent.run(
        "Research NVIDIA's current position and publish a three-bullet brief "
        "titled 'NVDA snapshot'.",
        session_id=session_id,
    )

    if run_response.content:
        pprint.pprint_run_response(run_response)

    pending_requirements = list(run_response.active_requirements or [])
    if not pending_requirements:
        raise RuntimeError("Expected the run to pause for publication approval")

    for requirement in pending_requirements:
        if not requirement.needs_confirmation:
            continue

        console.print(
            "\n[bold yellow]Confirmation Required[/bold yellow]\n"
            f"Tool: [bold blue]{requirement.tool_execution.tool_name}[/bold blue]\n"
            f"Args: {requirement.tool_execution.tool_args}"
        )
        choice = Prompt.ask(
            "Continue?",
            choices=["y", "n"],
            default="y",
        )

        if choice == "y":
            requirement.confirm()
            console.print("[green]Approved[/green]")
        else:
            requirement.reject()
            console.print("[red]Rejected[/red]")

    final_response = human_in_the_loop_agent.continue_run(
        run_id=run_response.run_id,
        session_id=session_id,
        requirements=run_response.requirements,
    )
    pprint.pprint_run_response(final_response)

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Apply this pattern to any tool whose effect deserves review:

1. Mark the tool with @tool(requires_confirmation=True)
2. Start the run with agent.run()
3. Show each pending requirement and its arguments
4. Call requirement.confirm() or requirement.reject()
5. Resume with agent.continue_run()

Typical approval gates:
- Send an email or publish content
- Write to a production database
- Create a purchase or financial transaction
- Deploy code or change infrastructure
- Delete or overwrite user data
"""
