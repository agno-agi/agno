"""
Setup:
1. Generate an App Password:
   - Go to "Personal Bitbucket settings" -> "App passwords"
   - Create a new App password with the appropriate permissions

2. Set environment variables:
   - BITBUCKET_USERNAME: Your Bitbucket username
   - BITBUCKET_PASSWORD: Your generated App password
"""

from agno.agent import Agent
from agno.tools.bitbucket import BitbucketTools

repo_slug = "ai"
workspace = "MaximMFP"

agent = Agent(
    tools=[BitbucketTools(workspace=workspace, repo_slug=repo_slug)],
)

agent.print_response("List open pull requests", markdown=True)

# Example 1: Get specific pull request details
# agent.print_response("Get details of pull request #23", markdown=True)

# Example 2: Get the repo details
# agent.print_response("Get details of the repository", markdown=True)

# Example 3: List repositories
# agent.print_response("List 5 repositories for this workspace", markdown=True)

# Example 4: List commits
# agent.print_response("List the last 20 commits", markdown=True)
