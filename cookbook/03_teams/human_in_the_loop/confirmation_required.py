"""Team HITL: Member agent tool requiring confirmation before execution.

This example demonstrates how a team pauses when a member agent's tool
requires human confirmation. After confirmation the team resumes with
continue_run().
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools import tool


@tool(requires_confirmation=True)
def deploy_to_production(app_name: str, version: str) -> str:
    """Deploy an application to production.

    Args:
        app_name (str): Name of the application
        version (str): Version to deploy
    """
    return f"Successfully deployed {app_name} v{version} to production"


deploy_agent = Agent(
    name="Deploy Agent",
    role="Handles deployments to production",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[deploy_to_production],
)

team = Team(
    name="DevOps Team",
    members=[deploy_agent],
    model=OpenAIChat(id="gpt-4o-mini"),
)

response = team.run("Deploy the payments app version 2.1 to production")

if response.is_paused:
    print("Team paused - requires confirmation")
    for req in response.requirements:
        if req.needs_confirmation:
            print(f"  Tool: {req.tool_execution.tool_name}")
            print(f"  Args: {req.tool_execution.tool_args}")
            req.confirm()

    response = team.continue_run(response)
    print(f"Result: {response.content}")
else:
    print(f"Result: {response.content}")
