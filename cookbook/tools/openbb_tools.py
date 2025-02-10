from agno.agent import Agent
from agno.tools.openbb import OpenBBTools

agent = Agent(tools=[OpenBBTools()], debug_mode=True, show_tool_calls=True)

# Example usage showing stock analysis
agent.print_response(
    "Get me the current stock price and key information for Apple (AAPL)"
)

# Example showing market analysis
agent.print_response("What are the top gainers in the market today?")

# Example showing economic indicators
agent.print_response(
    "Show me the latest GDP growth rate and inflation numbers for the US"
)
