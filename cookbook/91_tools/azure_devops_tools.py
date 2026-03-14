"""Azure DevOps Tools - Cookbook Example

Prerequisites:
    pip install -U agno azure-devops google-genai

Environment Variables:
    export AZURE_DEVOPS_ORG_URL="https://dev.azure.com/your-org"
    export AZURE_DEVOPS_PAT="your-personal-access-token"
    export AZURE_DEVOPS_PROJECT="your-project"
    export GOOGLE_API_KEY="your-google-api-key"
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.azure_devops import AzureDevOpsTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-2.5-flash"),
    tools=[
        AzureDevOpsTools(
            include_tools=[
                "list_projects",
                "list_repositories",
                "list_pull_requests",
                "list_work_items",
                "get_work_item",
                "list_pipelines",
                "get_pipeline_runs",
            ]
        )
    ],
    instructions=[
        "Use your tools to answer questions about Azure DevOps projects.",
        "Do not create, update, or delete anything unless explicitly asked.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("List all projects in the organization", markdown=True)

    # Example: List repositories
    # agent.print_response("List all repositories in the project", markdown=True)

    # Example: Pull requests
    # agent.print_response("List open pull requests", markdown=True)

    # Example: Work items
    # agent.print_response("Show all active bugs", markdown=True)

    # Example: Pipeline status
    # agent.print_response("Show recent runs for pipeline ID 5", markdown=True)
