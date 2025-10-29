from agno.agent import Agent
from agno.tools.openbb import OpenBBTools

# Example 1: Enable all OpenBB functions
agent_all = Agent(
    tools=[
        OpenBBTools(
            all=True,  # Enable all OpenBB financial data functions
        )
    ],
    markdown=True,
)

# Example 2: Enable specific OpenBB functions only
agent_specific = Agent(
    tools=[
        OpenBBTools(
            enable_get_stock_price=True,
            enable_search_company_symbol=True,
            enable_get_company_news=True,
            enable_get_company_profile=True,
            enable_get_price_targets=True,
        )
    ],
    markdown=True,
)

# Example 3: Default behavior with all functions enabled
agent = Agent(
    tools=[
        OpenBBTools(
            enable_get_stock_price=True,
            enable_search_company_symbol=True,
            enable_get_company_news=False,
            enable_get_company_profile=False,
            enable_get_price_targets=False,
        )
    ],
    markdown=True,
)

# Example usage with all functions enabled
print("=== Example 1: Using all OpenBB functions ===")
agent_all.print_response(
    "Provide a comprehensive analysis of Apple (AAPL) including current price, historical data, news, and ratios"
)

# Example usage with specific functions only
print(
    "\n=== Example 2: Using specific OpenBB functions (company info + historical data) ==="
)
agent_specific.print_response(
    "Get company information and historical stock data for Tesla (TSLA)"
)

# Example usage with default configuration
print("\n=== Example 3: Default OpenBB agent usage ===")
agent.print_response(
    "Get me the current stock price and key information for Apple (AAPL)"
)

agent.print_response("What are the top gainers in the market today?")

agent.print_response(
    "Show me the latest GDP growth rate and inflation numbers for the US"
)
