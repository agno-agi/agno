"""🤝 Human-in-the-Loop: Adding User Confirmation to Tool Calls

This example shows how to implement human-in-the-loop functionality in your Agno tools.
It shows how to:
- Handle user confirmation during tool execution
- Gracefully cancel operations based on user choice

Some practical applications:
- Confirming sensitive operations before execution
- Reviewing API calls before they're made
- Validating data transformations
- Approving automated actions in critical systems

Run `pip install openai httpx rich agno` to install dependencies.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils import pprint
from rich.console import Console
from rich.prompt import Prompt

console = Console()

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools(requires_confirmation_tools=["duckduckgo_search"])],
    markdown=True,
    db=SqliteDb(db_file="tmp/confirmation_required_toolkit.db"),
)

run_response = agent.run("What is the current stock price of Apple?")
if run_response.is_paused:  # Or agent.run_response.is_paused
    for requirement in run_response.active_requirements:
        if requirement.needs_confirmation:
            # Ask for confirmation
            console.print(
                f"Tool name [bold blue]{requirement.tool_execution.tool_name}({requirement.tool_execution.tool_args})[/] requires confirmation."
            )
            message = (
                Prompt.ask("Do you want to continue?", choices=["y", "n"], default="y")
                .strip()
                .lower()
            )

            if message == "n":
                requirement.reject()
            else:
                requirement.confirm()

    run_response = agent.continue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )
    pprint.pprint_run_response(run_response)
