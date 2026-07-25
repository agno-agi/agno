"""
Azure DevOps Repos Tools

Setup:
1. Create a personal access token (PAT) in Azure DevOps with Code (read) scope.
2. Set environment variables:
   - AZURE_DEVOPS_ORG_URL: Your organization URL (e.g. https://dev.azure.com/my-org)
   - AZURE_DEVOPS_PAT: Your personal access token
   - AZURE_DEVOPS_PROJECT: Default project name or ID
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.azure_devops import AzureDevOpsReposTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "Use Azure DevOps repository tools to answer questions about code repositories.",
    ],
    tools=[AzureDevOpsReposTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "List the repositories in the project and show the file tree of the first one."
    )
