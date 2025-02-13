# from ...libs.agno.agno.tools.bitbucket import BitbucketTools
from agno.agent import Agent
from agno.tools.bitbucket import BitbucketTools

repo_slug = "Your Repository Slug"
workspace = "Your Workspace"

agent = Agent(
    instructions=[
        f"Use your tools to answer questions about the repo {repo_slug} in the {workspace} workspace",
        "Do not create any issues or pull requests unless explicitly asked to do so",
    ],
    tools=[BitbucketTools()],
    show_tool_calls=True,
)

# Example usage: List all the open pull requests
# agent.print_response("List open pull requests", markdown=True)

# Example usage: Get pull request details
# agent.print_response("Get details of #230", markdown=True)

# Example usage: Get pull request changes
# agent.print_response("Show changes for #230", markdown=True)

# Example usage: List open issues. Only works if the repository has issues enabled
# agent.print_response("What is the latest opened issue?", markdown=True)

# Example usage: Get the repo details
# agent.print_response("Get details of the repository", markdown=True)

# Example usage: List all the repositories
# agent.print_response("List 5 repositories for this workspace", markdown=True)

# Example usage: Create a Repo. Needs Admin Repository access when using App Password
# agent.print_response(
#     "Create a repo called agent-testing and add description hello", markdown=True
# )
