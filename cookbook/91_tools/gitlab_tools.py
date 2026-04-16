"""
GitLab Tools

Setup:
1. Create a personal access token in GitLab with read scopes.
2. Set environment variables:
   - GITLAB_ACCESS_TOKEN: Your token
   - GITLAB_BASE_URL: Optional GitLab URL (defaults to https://gitlab.com)
"""

from agno.agent import Agent
from agno.tools.gitlab import GitlabTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    instructions=[
        "Use GitLab tools to answer repository questions.",
        "Use read-only operations unless explicitly asked to modify data.",
    ],
    tools=[
        GitlabTools(
            enable_list_projects=True,
            enable_get_projects=True,
            enable_list_merge_requests=True,
            enable_get_merge_request=True,
            enable_list_issues=True,
        )
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "List open merge requests for project 'gitlab-org/gitlab' and summarize the top 5 by recency.",
        markdown=True,
    )

    # Async variant:
    # import asyncio
    #
    # async def run_async():
    #     await agent.aprint_response(
    #         "List open issues for project 'gitlab-org/gitlab' with labels and assignees.",
    #         markdown=True,
    #     )
    #
    # asyncio.run(run_async())
