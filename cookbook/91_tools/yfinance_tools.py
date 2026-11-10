"""
YFinance Tools - Stock Market Analysis and Financial Data

This example demonstrates how to use YFinanceTools for financial analysis,
showing different patterns for selective function access using boolean flags.

Run: `uv pip install yfinance` to install the dependencies
"""

from agno.agent import Agent
from agno.tools.yfinance import YFinanceTools
from curl_cffi.requests import Session

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: All financial functions available
agent_full = Agent(
    tools=[YFinanceTools(all=True)],  # All functions enabled
    description="You are a comprehensive investment analyst with access to all financial data functions.",
    instructions=[
        "Use any financial function as needed for investment analysis",
        "Format your response using markdown and use tables to display data",
        "Provide detailed analysis and insights based on the data",
        "Include relevant financial metrics and recommendations",
    ],
    markdown=True,
)

# Example 2: Enable only basic stock information
agent_basic = Agent(
    tools=[
        YFinanceTools(
            enable_stock_price=True,
            enable_company_info=True,
            enable_historical_prices=True,
        )
    ],
    description="You are a basic stock information specialist focused on price and historical data.",
    instructions=[
        "Provide current stock prices and basic company information",
        "Show historical price trends when requested",
        "Keep analysis focused on price movements and basic metrics",
        "Format data clearly using tables",
    ],
    markdown=True,
)

# Example 3: Enable most tools except complex financial analysis functions
agent_simple = Agent(
    tools=[
        YFinanceTools(
            enable_stock_price=True,
            enable_company_info=True,
            enable_stock_fundamentals=True,
            enable_analyst_recommendations=True,
            enable_company_news=True,
            enable_technical_indicators=True,
            enable_historical_prices=True,
            # Excluding: enable_income_statements and enable_key_financial_ratios
        )
    ],
    description="You are a stock analyst focused on market data without complex financial statements.",
    instructions=[
        "Provide stock prices, recommendations, and market trends",
        "Avoid complex financial statement analysis",
        "Focus on actionable market information",
        "Keep analysis accessible to general investors",
    ],
    markdown=True,
)

# Example 4: Enable only analysis and recommendation functions
agent_analyst = Agent(
    tools=[
        YFinanceTools(
            enable_stock_price=True,
            enable_analyst_recommendations=True,
            enable_company_news=True,
        )
    ],
    description="You are an equity research analyst focused on recommendations and market sentiment.",
    instructions=[
        "Provide analyst recommendations and price targets",
        "Include relevant news and market sentiment",
        "Focus on forward-looking analysis and earnings expectations",
        "Present information suitable for investment decisions",
    ],
    markdown=True,
)


# If you want to disable SSL verification, you can do it like this:
session = Session()
session.verify = False  # Disable SSL verification (use with caution)
yfinance_tools = YFinanceTools(all=True, session=session)
agent_ssl_disabled = Agent(
    tools=[yfinance_tools],  # All functions enabled
    description="You are a comprehensive investment analyst with access to all financial data functions.",
    instructions=[
        "Use any financial function as needed for investment analysis",
        "Format your response using markdown and use tables to display data",
        "Provide detailed analysis and insights based on the data",
        "Include relevant financial metrics and recommendations",
    ],
    markdown=True,
)

# Using the basic agent for the main example

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Basic Stock Analysis Example ===")
    agent_basic.print_response(
        "Share the NVDA stock price and recent historical performance", markdown=True
    )

    print("\n=== Analyst Recommendations Example ===")
    agent_analyst.print_response(
        "Get analyst recommendations and recent news for AAPL", markdown=True
    )

    print("\n=== Full Analysis Example ===")
    agent_full.print_response(
        "Provide a comprehensive analysis of TSLA including price, fundamentals, and analyst views",
        markdown=True,
    )

    print("\n=== Full Analysis Example ===")
    agent_simple.print_response(
        "Provide a comprehensive analysis of TSLA including price, fundamentals, and analyst views",
        markdown=True,
    )

    print("\n=== SSL Disabled Example ===")
    agent_ssl_disabled.print_response(
        "What is the stock price of TSLA?",
        markdown=True,
    )
