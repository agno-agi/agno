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


agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[get_user_location, get_current_date],
    markdown=True,
    db=SqliteDb(session_table="mixed_tools_session", db_file="tmp/mixed_tools.db"),
)

if __name__ == "__main__":
    run_response = agent.run("What is the current date and time in my location?")
    pprint.pprint_run_response(run_response)

