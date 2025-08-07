from agno.agent import Agent
from agno.tools.brandfetch import BrandfetchTools

agent = Agent(
    tools=[BrandfetchTools()],
    show_tool_calls=True,
    description="You are a Brand research agent. Given a company name or company domain, you will use the Brandfetch API to retrieve the company's brand information.",
)
agent.print_response("What is the brand information of Google?", markdown=True)
