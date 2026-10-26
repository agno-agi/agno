"""
Finnhub MCP Server - Model Context Protocol Implementation

Provides standardized access to Finnhub financial data via MCP tools:
- get_company_profile: Company fundamentals
- get_stock_quote: Real-time market data
- get_financial_metrics: Financial ratios and valuation
- get_company_news: Recent news and sentiment
"""

import os
import sys
import requests
from datetime import datetime, timedelta, timezone
from fastmcp import FastMCP

# Finnhub API configuration
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
BASE_URL = "https://finnhub.io/api/v1"


def fetch_finnhub(path: str, **params) -> dict:
    """Fetch data from Finnhub API with error handling."""
    if not FINNHUB_API_KEY:
        return {"error": "FINNHUB_API_KEY not set"}

    params["token"] = FINNHUB_API_KEY
    
    try:
        response = requests.get(f"{BASE_URL}{path}", params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        return {"error": str(e)}


# MCP server
mcp = FastMCP("Finnhub Financial Data")


@mcp.tool()
def get_company_profile(ticker: str) -> dict:
    """
    Get company profile and fundamental information.
    
    Args:
        ticker (str): Stock symbol (e.g., 'AAPL', 'GOOGL'). Case-insensitive.
    
    Returns:
        dict: Company data including name, industry, market cap, website,
              description, exchange, and corporate details.
    
    Example:
        get_company_profile("AAPL") returns Apple's profile data.
    """
    ticker = ticker.upper()
    return fetch_finnhub("/stock/profile2", symbol=ticker)


@mcp.tool()
def get_stock_quote(ticker: str) -> dict:
    """
    Get real-time stock price and trading data.
    
    Args:
        ticker (str): Stock symbol (e.g., 'AAPL', 'GOOGL'). Case-insensitive.
    
    Returns:
        dict: Current price, day's high/low, volume, change, and previous close.
    
    Note: Real-time data may have 15-minute delay for some exchanges.
    """
    ticker = ticker.upper()
    return fetch_finnhub("/quote", symbol=ticker)


@mcp.tool()
def get_financial_metrics(ticker: str) -> dict:
    """
    Get financial metrics and valuation ratios for fundamental analysis.
    
    Args:
        ticker (str): Stock symbol (e.g., 'AAPL', 'GOOGL'). Case-insensitive.
    
    Returns:
        dict: Financial data including P/E ratios, margins, ROE, debt ratios,
              growth rates, and dividend information.
    
    Example:
        get_financial_metrics("AAPL") returns Apple's valuation and profitability metrics.
    """
    ticker = ticker.upper()
    return fetch_finnhub("/stock/metric", symbol=ticker, metric="all")


@mcp.tool()
def get_company_news(ticker: str) -> dict:
    """
    Get recent news articles for a company from the past 30 days.
    
    Args:
        ticker (str): Stock symbol (e.g., 'AAPL', 'GOOGL'). Case-insensitive.
    
    Returns:
        dict: List of up to 50 recent articles with headline, source, summary,
              publication date, and URL.
    
    Use for: Earnings news, product launches, management changes, sentiment analysis.
    """
    ticker = ticker.upper()
    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=30)
    return fetch_finnhub("/company-news", symbol=ticker, _from=str(from_date), to=str(to_date))


if __name__ == "__main__":
    # Server startup
    print("Finnhub MCP server started successfully", file=sys.stderr)
    mcp.run()
