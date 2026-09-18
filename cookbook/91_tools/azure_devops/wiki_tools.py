"""
Azure DevOps Wiki Tools

Setup:
1. Create a personal access token (PAT) in Azure DevOps with Wiki (read) scope.
2. Set environment variables:
   - AZURE_DEVOPS_ORG_URL: Your organization URL (e.g. https://dev.azure.com/my-org)
   - AZURE_DEVOPS_PAT: Your personal access token
   - AZURE_DEVOPS_PROJECT: Default project name or ID
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.azure_devops import AzureDevOpsWikiTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "Use Azure DevOps wiki tools to find and summarize documentation.",
    ],
    tools=[AzureDevOpsWikiTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "List the wikis in the project and search the first wiki for pages about onboarding."
    )
