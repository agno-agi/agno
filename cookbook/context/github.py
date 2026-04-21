"""
GitHub Context Provider
=======================

Read-only GitHub access — search repos/code/issues, read files and PRs.
Write tools (create_issue, close_issue, delete_repository, etc.) are
filtered out.

Run: pip install openai pygithub
Env: GITHUB_ACCESS_TOKEN, OPENAI_API_KEY
"""

from agno.agent import Agent
from agno.context.github import GitHubContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Build Provider
# ---------------------------------------------------------------------------
provider = GitHubContextProvider()

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=provider.get_tools(),
    instructions=[
        "You answer questions about public GitHub repositories.",
        provider.instructions(),
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Status:", provider.status())
    agent.print_response(
        "List the top three recently opened issues on agno-agi/agno.",
        stream=True,
    )
