from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(tools=[DuckDuckGoTools()], show_tool_calls=True)
agent.print_response("Whats happening in France?", markdown=True)

# We will search DDG but limit the site to Politifact
agent = Agent(
    tools=[DuckDuckGoTools(modifier="site:politifact.com")], show_tool_calls=True
)
agent.print_response(
    "Is Taylor Swift promoting energy-saving devices with Elon Musk?", markdown=False
)
