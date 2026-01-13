from agno.agent import Agent
from composio_agno import Action, ComposioToolSet

toolset = ComposioToolSet()
composio_tools = toolset.get_tools(
    actions=[Action.GITHUB_STAR_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER]
)
agent = Agent(tools=composio_tools)

agent.print_response("Can you star agno-agi/agno repo?")
