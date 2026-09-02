"""
Azure Repos Tools

Read, review, and manage Azure DevOps Git repositories from an agent.

Setup:
1. Create a Personal Access Token (PAT) in Azure DevOps:
   a. Sign in at https://dev.azure.com/<your-org>
   b. Click your profile icon (top right) -> Personal access tokens -> New Token
   c. Choose scopes:
      - Code: Read              (read-only flows)
      - Code: Read & write      (create branches, PRs, comments)
      - Code: Full              (only if you also need to delete repos / branches)
   d. Set an expiration and copy the token (shown only once)

2. Provision an Azure AI Foundry model deployment (used as the agent's brain):
   a. In Azure AI Foundry, deploy a chat model and copy its endpoint + key.
   b. Note the deployment name (e.g. `gpt-5.5` or whatever you deployed).

3. Set environment variables:

   # Azure DevOps (Repos)
   export AZURE_DEVOPS_ORG_URL="https://dev.azure.com/<your-org>"
   export AZURE_DEVOPS_PAT="<your-pat>"
   export AZURE_DEVOPS_PROJECT="<default-project>"          # optional fallback

   # Azure DevOps Server (on-prem) instead of dev.azure.com
   export AZURE_DEVOPS_ORG_URL="https://devops.example.com/<collection>"

   # Azure AI Foundry (model)
   export AZURE_API_KEY="<foundry-api-key>"
   export AZURE_ENDPOINT="https://<your-resource>.services.ai.azure.com/models"
   export AZURE_API_VERSION="2024-05-01-preview"            # optional, sensible default

4. Install runtime dependencies:
   pip install httpx azure-ai-inference

5. Run with the demo virtual environment:
   .venvs/demo/bin/python cookbook/91_tools/azure_repos_tools.py
"""

from agno.agent import Agent
from agno.models.azure import AzureAIFoundry
from agno.tools.azure_repos import AzureReposTools
from dotenv import load_dotenv

# Replace with the deployment name you provisioned in Azure AI Foundry.
FOUNDRY_MODEL_ID = "gpt-4.1"

load_dotenv()

# ---------------------------------------------------------------------------
# Example 1: Read-only agent (recommended starting point)
#   Uses include_tools to expose only safe lookups. Cannot create or modify
#   anything regardless of the toolkit's defaults.
# ---------------------------------------------------------------------------

read_only_agent = Agent(
    model=AzureAIFoundry(id=FOUNDRY_MODEL_ID),
    instructions=[
        "Use Azure Repos tools to answer questions about repositories, branches, pull requests, commits, and files.",
        "You can only read data. Do not attempt to create, update, or delete anything.",
        "When the user asks about a repository or PR by name, prefer the project from the environment unless they specify one.",
    ],
    tools=[
        AzureReposTools(
            include_tools=[
                "list_repositories",
                "get_repository",
                "list_branches",
                "list_pull_requests",
                "get_pull_request",
                "get_pull_request_commits",
                "list_pull_request_threads",
                "list_commits",
                "get_file_content",
                "list_items",
            ]
        )
    ],
    debug_mode=True,
)


# ---------------------------------------------------------------------------
# Example 2: Maintainer agent (read + non-destructive writes)
#   Default flag set: list/get/read + create_*. delete_* stays off.
# ---------------------------------------------------------------------------

maintainer_agent = Agent(
    model=AzureAIFoundry(id=FOUNDRY_MODEL_ID),
    instructions=[
        "You are a repository maintainer assistant for Azure DevOps.",
        "You can read repository data and create new branches, pull requests, and PR comments.",
        "Never delete a repository or branch. Refuse and explain if asked.",
    ],
    tools=[AzureReposTools()],
)


# ---------------------------------------------------------------------------
# Example 3: Admin agent (everything, including destructive ops)
#   Destructive operations are off by default; opt in explicitly.
# ---------------------------------------------------------------------------

admin_agent = Agent(
    model=AzureAIFoundry(id=FOUNDRY_MODEL_ID),
    instructions=[
        "You are an Azure Repos administrator.",
        "You may delete repositories and branches.",
        "Always confirm the target name and project in your response before performing a destructive action.",
    ],
    tools=[
        AzureReposTools(
            enable_delete_repository=True,  # destructive, off by default
            enable_delete_branch=True,  # destructive, off by default
        )
    ],
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Default run: a read-only summary against the configured project.
    read_only_agent.print_response(
        "List the Git repositories in the default project and summarize the top 5 by name and default branch.",
        markdown=True,
    )

    # ------------------------------------------------------------------
    # Read-only examples (uncomment to try)
    # ------------------------------------------------------------------

    # # List active pull requests for a specific repository
    # read_only_agent.print_response(
    #     "List active pull requests in the 'demo' repository, grouped by author.",
    #     markdown=True,
    # )

    # # Get details for a specific pull request
    # read_only_agent.print_response(
    #     "Get details for pull request #42 and summarize its title, status, and source/target branches.",
    #     markdown=True,
    # )

    # # Inspect commits on a pull request
    # read_only_agent.print_response(
    #     "Show the commits for pull request #42 in the 'demo' repository.",
    #     markdown=True,
    # )

    # # Read review threads on a pull request
    # read_only_agent.print_response(
    #     "List comment threads on pull request #42 in the 'demo' repository and summarize unresolved threads.",
    #     markdown=True,
    # )

    # # List branches
    # read_only_agent.print_response(
    #     "List all branches in the 'demo' repository.",
    #     markdown=True,
    # )

    # # List recent commits on a branch
    # read_only_agent.print_response(
    #     "Show the 10 most recent commits on the 'main' branch of the 'demo' repository.",
    #     markdown=True,
    # )

    # # Read a file
    # read_only_agent.print_response(
    #     "Show me the content of /README.md in the 'demo' repository on the main branch.",
    #     markdown=True,
    # )

    # # List items at a path
    # read_only_agent.print_response(
    #     "List the files and folders under /src in the 'demo' repository on the main branch.",
    #     markdown=True,
    # )

    # ------------------------------------------------------------------
    # Maintainer write examples (uncomment to try)
    # ------------------------------------------------------------------

    # # Create a new branch from main
    # maintainer_agent.print_response(
    #     "Create a new branch named 'feature/agent-experiment' from 'main' in the 'demo' repository.",
    #     markdown=True,
    # )

    # # Open a draft pull request
    # maintainer_agent.print_response(
    #     "Open a draft pull request from 'feature/agent-experiment' into 'main' in the 'demo' repository, "
    #     "title 'Experiment: agent-driven changes', description 'Initial scaffolding'.",
    #     markdown=True,
    # )

    # # Comment on a pull request
    # maintainer_agent.print_response(
    #     "Add a comment 'Looks good, just one nit on naming.' to pull request #42 in the 'demo' repository.",
    #     markdown=True,
    # )

    # ------------------------------------------------------------------
    # Admin destructive examples (uncomment to try; double-check first)
    # ------------------------------------------------------------------

    # # Delete a feature branch after merge
    # admin_agent.print_response(
    #     "Delete the 'feature/agent-experiment' branch from the 'demo' repository.",
    #     markdown=True,
    # )

    # ------------------------------------------------------------------
    # Async usage
    # ------------------------------------------------------------------

    # import asyncio
    #
    # async def run_async():
    #     await read_only_agent.aprint_response(
    #         "List branches in the 'demo' repository and pick the most recently updated one.",
    #         markdown=True,
    #     )
    #
    # asyncio.run(run_async())
