"""
Azure DevOps Boards Tools

Setup:
1. Create a personal access token (PAT) in Azure DevOps with Work Items (read and write) scope.
2. Set environment variables:
   - AZURE_DEVOPS_ORG_URL: Your organization URL (e.g. https://dev.azure.com/my-org)
   - AZURE_DEVOPS_PAT: Your personal access token
   - AZURE_DEVOPS_PROJECT: Default project name or ID
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.azure_devops import AzureDevOpsBoardsTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "Use Azure DevOps boards tools to manage work items, sprints and comments.",
        "Use read-only operations unless explicitly asked to create or update work items.",
    ],
    tools=[AzureDevOpsBoardsTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "List the current sprints and show the work items in the active sprint."
    )
