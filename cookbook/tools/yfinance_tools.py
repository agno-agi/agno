"""
YFinance Tools - Stock Market Analysis and Financial Data

This example demonstrates how to use YFinanceTools for financial analysis,
showing include_tools/exclude_tools patterns for selective function access.
YFinanceTools is a large tool (≥6 functions) so it uses include_tools/exclude_tools.

Run: `pip install yfinance` to install the dependencies
"""

from agno.agent import Agent
from agno.tools.yfinance import YFinanceTools

# Example 1: All financial functions available (default behavior)
agent_full = Agent(
    tools=[YFinanceTools()],  # All functions enabled by default
    description="You are a comprehensive investment analyst with access to all financial data functions.",
    instructions=[
        "Use any financial function as needed for investment analysis",
        "Format your response using markdown and use tables to display data",
        "Provide detailed analysis and insights based on the data",
        "Include relevant financial metrics and recommendations",
    ],
    markdown=True,
)

# Example 2: Include only basic stock information
agent_basic = Agent(
    tools=[YFinanceTools(
        include_tools=[
            "get_stock_price",
            "get_stock_info",
            "get_historical_data"
        ]
    )],
    description="You are a basic stock information specialist focused on price and historical data.",
    instructions=[
        "Provide current stock prices and basic company information",
        "Show historical price trends when requested",
        "Keep analysis focused on price movements and basic metrics",
        "Format data clearly using tables",
    ],
    markdown=True,
)

# Example 3: Exclude complex financial analysis functions
agent_simple = Agent(
    tools=[YFinanceTools(
        exclude_tools=[
            "get_financials",           # Complex financial statements
            "get_balance_sheet",        # Detailed balance sheet data
            "get_cash_flow",           # Cash flow statements
            "get_major_holders",       # Ownership data
        ]
    )],
    description="You are a stock analyst focused on market data without complex financial statements.",
    instructions=[
        "Provide stock prices, recommendations, and market trends",
        "Avoid complex financial statement analysis",
        "Focus on actionable market information",
        "Keep analysis accessible to general investors",
    ],
    markdown=True,
)

# Example 4: Include only analysis and recommendation functions
agent_analyst = Agent(
    tools=[YFinanceTools(
        include_tools=[
            "get_analyst_recommendations",
            "get_stock_news",
            "get_earnings_calendar",
            "get_stock_price"
        ]
    )],
    description="You are an equity research analyst focused on recommendations and market sentiment.",
    instructions=[
        "Provide analyst recommendations and price targets",
        "Include relevant news and market sentiment",
        "Focus on forward-looking analysis and earnings expectations",
        "Present information suitable for investment decisions",
    ],
    markdown=True,
)

# Using the basic agent for the main example
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
    markdown=True
)
