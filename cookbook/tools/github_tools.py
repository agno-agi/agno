from agno.agent import Agent
from agno.tools.github import GithubTools

agent = Agent(
    instructions=[
        "Use your tools to answer questions about the repo: agno-agi/agno",
        "Do not create any issues or pull requests unless explicitly asked to do so",
    ],
    tools=[GithubTools()],
    show_tool_calls=True,
)
agent.print_response("List open pull requests", markdown=True)

# # Example usage: Search for python projects on github that have more than 1000 stars
# agent.print_response("Search for python projects on github that have more than 1000 stars", markdown=True, stream=True)

# # Example usage: Search for python projects on github that have more than 1000 stars, but return the 2nd page of results
# agent.print_response("Search for python projects on github that have more than 1000 stars, but return the 2nd page of results", markdown=True, stream=True)

# # Example usage: Get pull request details
# agent.print_response("Get details of #1239", markdown=True)

# # Example usage: Get pull request changes
# agent.print_response("Show changes for #1239", markdown=True)

# # Example usage: List open issues
# agent.print_response("What is the latest opened issue?", markdown=True)

# # Example usage: Create an issue
# agent.print_response("Explain the comments for the most recent issue", markdown=True)

# # Example usage: Create a Repo
# agent.print_response("Create a repo called agno-test and add description hello", markdown=True)
