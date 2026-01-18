"""
Financial Datasets API Toolkit Example
This example demonstrates various Financial Datasets API functionalities including
financial statements, stock prices, news, insider trades, and more.

Prerequisites:
- Set the environment variable `FINANCIAL_DATASETS_API_KEY` with your Financial Datasets API key.
  You can obtain the API key by creating an account at https://financialdatasets.ai
"""

from agno.agent import Agent
from agno.tools.financial_datasets import FinancialDatasetsTools

agent = Agent(
    name="Financial Data Agent",
    tools=[
        FinancialDatasetsTools(),  # For accessing financial data
    ],
    description="You are a financial data specialist that helps analyze financial information for stocks and cryptocurrencies.",
    instructions=[
        "When given a financial query:",
        "1. Use appropriate Financial Datasets methods based on the query type",
        "2. Format financial data clearly and highlight key metrics",
        "3. For financial statements, compare important metrics with previous periods when relevant",
        "4. Calculate growth rates and trends when appropriate",
        "5. Handle errors gracefully and provide meaningful feedback",
    ],
    markdown=True,
)

# Example 1: Financial Statements
print("\n=== Income Statement Example ===")
agent.print_response(
    "Get the most recent income statement for AAPL and highlight key metrics",
    stream=True,
)

# Example 2: Balance Sheet Analysis
print("\n=== Balance Sheet Analysis Example ===")
agent.print_response(
    "Analyze the balance sheets for MSFT over the last 3 years. Focus on debt-to-equity ratio and cash position.",
    stream=True,
)

# # Example 3: Cash Flow Analysis
# print("\n=== Cash Flow Analysis Example ===")
# agent.print_response(
#     "Get the quarterly cash flow statements for TSLA for the past year and analyze their free cash flow trends",
#     stream=True,
# )

# # Example 4: Company Information
# print("\n=== Company Information Example ===")
# agent.print_response(
#     "Provide key information about NVDA including its business description, sector, and industry",
#     stream=True,
# )

# # Example 5: Stock Price Analysis
# print("\n=== Stock Price Analysis Example ===")
# agent.print_response(
#     "Analyze the daily stock prices for AMZN over the past 30 days. Calculate the average, high, low, and volatility.",
#     stream=True,
# )

# # Example 6: Earnings Comparison
# print("\n=== Earnings Comparison Example ===")
# agent.print_response(
#     "Compare the last 4 earnings reports for GOOG. Show the trend in EPS and revenue.",
#     stream=True,
# )

# # Example 7: Insider Trades Analysis
# print("\n=== Insider Trades Analysis Example ===")
# agent.print_response(
#     "Analyze recent insider trading activity for META. Are insiders buying or selling?",
#     stream=True,
# )

# # Example 8: Institutional Ownership
# print("\n=== Institutional Ownership Example ===")
# agent.print_response(
#     "Who are the largest institutional owners of INTC? Have they increased or decreased their positions recently?",
#     stream=True,
# )

# # Example 9: Financial News
# print("\n=== Financial News Example ===")
# agent.print_response(
#     "What are the latest news items about NFLX? Summarize the key stories.",
#     stream=True,
# )

# # Example 10: Multi-stock Comparison
# print("\n=== Multi-stock Comparison Example ===")
# agent.print_response(
#     """Compare the following tech companies: AAPL, MSFT, GOOG, AMZN, META
#     1. Revenue growth rate
#     2. Profit margins
#     3. P/E ratios
#     4. Debt levels
#     Present as a comparison table.""",
#     stream=True,
# )

# # Example 11: Cryptocurrency Analysis
# print("\n=== Cryptocurrency Analysis Example ===")
# agent.print_response(
#     "Analyze Bitcoin (BTC) price movements over the past week. Show daily price changes and calculate volatility.",
#     stream=True,
# )

# # Example 12: SEC Filings Analysis
# print("\n=== SEC Filings Analysis Example ===")
# agent.print_response(
#     "Get the most recent 10-K and 10-Q filings for AAPL and extract key risk factors mentioned.",
#     stream=True,
# )

# # Example 13: Financial Metrics and Ratios
# print("\n=== Financial Metrics Example ===")
# agent.print_response(
#     "Calculate and explain the following financial metrics for TSLA: P/E ratio, P/S ratio, EV/EBITDA, and ROE.",
#     stream=True,
# )

# # Example 14: Segmented Financials
# print("\n=== Segmented Financials Example ===")
# agent.print_response(
#     "Analyze AAPL's segmented financials. How much revenue comes from each product category and geographic region?",
#     stream=True,
# )

# # Example 15: Stock Ticker Search
# print("\n=== Stock Ticker Search Example ===")
# agent.print_response(
#     "Find all stock tickers related to 'artificial intelligence' and give me a brief overview of each company.",
#     stream=True,
# )

# # Example 16: Financial Statement Comparison
# print("\n=== Financial Statement Comparison Example ===")
# agent.print_response(
#     """Compare the financial statements of AAPL and MSFT for the most recent fiscal year:
#     1. Revenue and revenue growth
#     2. Net income and profit margins
#     3. Cash position and debt levels
#     4. R&D spending
#     Present the comparison in a well-formatted table.""",
#     stream=True,
# )

# # Example 17: Portfolio Analysis
# print("\n=== Portfolio Analysis Example ===")
# agent.print_response(
#     """Analyze a portfolio with the following stocks and weights:
#     - AAPL (25%)
#     - MSFT (25%)
#     - GOOG (20%)
#     - AMZN (15%)
#     - TSLA (15%)
#     Calculate the portfolio's overall financial metrics and recent performance.""",
#     stream=True,
# )

# # Example 18: Dividend Analysis
# print("\n=== Dividend Analysis Example ===")
# agent.print_response(
#     "Analyze the dividend history and dividend yield for JNJ over the past 5 years.",
#     stream=True,
# )

# # Example 19: Technical Indicator Analysis
# print("\n=== Technical Indicator Analysis Example ===")
# agent.print_response(
#     "Using daily stock prices for the past 30 days, calculate and interpret the 7-day and 21-day moving averages for AAPL.",
#     stream=True,
# )

# # Example 20: Financial Report Summary
# print("\n=== Financial Report Summary Example ===")
# agent.print_response(
#     """Create a comprehensive financial summary for NVDA including:
#     1. Company overview
#     2. Latest income statement highlights
#     3. Balance sheet strength
#     4. Cash flow analysis
#     5. Key financial ratios
#     6. Recent news affecting the stock""",
#     stream=True,
# )
