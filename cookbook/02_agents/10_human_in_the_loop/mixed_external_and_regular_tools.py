"""
Mixed External and Regular Tools
=============================

Human-in-the-Loop: Mix external_execution tools with regular tools in the same agent.
"""

import json
from datetime import datetime

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools import tool
from agno.utils import pprint


# A regular tool - the agent executes this automatically.
def get_current_date() -> str:
    """Get the current date and time.

    Returns:
        str: The current date and time in a human-readable format.
    """
    return datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")


# An external tool - the agent pauses and we execute it ourselves.
@tool(external_execution=True)
def get_user_location() -> str:
    """Get the user's current location.

    Returns:
        str: The user's current city and country.
    """
    return json.dumps({"city": "San Francisco", "country": "US"})


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[get_user_location, get_current_date],
    markdown=True,
    db=SqliteDb(session_table="mixed_tools_session", db_file="tmp/mixed_tools.db"),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_response = agent.run("What is the current date and time in my location?")

    if run_response.is_paused:
        for requirement in run_response.active_requirements:
            if requirement.needs_external_execution:
                if requirement.tool_execution.tool_name == get_user_location.name:
                    print(
                        f"Executing {requirement.tool_execution.tool_name} with args {requirement.tool_execution.tool_args} externally"
                    )
                    # We execute the tool ourselves. You can also execute something completely external here.
                    result = get_user_location.entrypoint(
                        **requirement.tool_execution.tool_args
                    )  # type: ignore
                    # We have to set the result on the tool execution object so that the agent can continue
                    requirement.set_external_execution_result(result)

        run_response = agent.continue_run(
            run_id=run_response.run_id,
            requirements=run_response.requirements,
        )

    pprint.pprint_run_response(run_response)

    # Or for simple debug flow
    # agent.print_response("What is the current date and time in my location?")
