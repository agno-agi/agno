"""
Redmine Tools
=============================

Demonstrates the Redmine tools for searching, reading, creating, updating, and commenting on issues.

Set the following environment variables before running:
- REDMINE_SERVER_URL
- REDMINE_TOKEN (or REDMINE_USERNAME and REDMINE_PASSWORD if you don't have a token)
"""

import os

from agno.agent import Agent
from agno.tools.redmine import RedmineTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Get Redmine connection details from environment
server_url = os.getenv("REDMINE_SERVER_URL")
token = os.getenv("REDMINE_TOKEN")

agent = Agent(
    name="Redmine agent",
    tools=[RedmineTools(server_url=server_url, token=token)],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # searching issues by subject
    agent.print_response("Find all issues whose subject contains 'search'")

    # getting issue details
    agent.print_response("Show me the details of issue 1")

    # creating a new issue
    agent.print_response(
        "Create a Bug in project 'website' titled 'Login button unresponsive' "
        "described 'The login button does nothing on click'"
    )

    # adding a comment
    agent.print_response("Add the comment 'Reviewed and confirmed' to issue 1")
