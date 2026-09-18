"""
Company Profiler Agent - Financial Data Acquisition

Primary data collection agent using MCP to interface with Finnhub API.
Extracts tickers, retrieves market data, and structures financial information.
"""

import os
from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters

# MCP server configuration
server_params = StdioServerParameters(
    command="python",
    args=["mcp/finnhub_mcp_server.py"],
    env={"FINNHUB_API_KEY": os.getenv("FINNHUB_API_KEY")},
)

# MCP tools with auto-connection
mcp_tools = MCPTools(server_params=server_params)

# Company Profiler agent
CompanyProfiler = Agent(
    name="Company Profiler",
    model=Gemini(id="gemini-2.5-flash", api_key=os.getenv("GEMINI_API_KEY")),
    tools=[mcp_tools],
    instructions=[
        "You are a financial data analyst responsible for gathering comprehensive company information.",
        "Your task is to extract the stock ticker symbol from the user's input and fetch essential company data.",
        "",
        "Step-by-step process:",
        "1. Identify the ticker symbol from the input text (examples: TSLA, AAPL, JPM, MSFT, GOOGL)",
        "2. Use get_company_profile tool to fetch company profile information",
        "3. Use get_stock_quote tool to get real-time stock price and trading data",
        "4. Use get_financial_metrics tool to fetch key financial metrics and ratios",
        "5. Combine all data into a structured JSON response",
        "",
        "Output format - Return ONLY this JSON structure:",
        "{",
        '  "ticker": "EXTRACTED_TICKER",',
        '  "profile": {company_profile_data_from_tool},',
        '  "quote": {real_time_quote_data_from_tool},',
        '  "metrics": {financial_metrics_data_from_tool}',
        "}",
        "",
        "Important notes:",
        "- Always extract the ticker in uppercase (e.g., 'tsla' becomes 'TSLA')",
        "- If ticker extraction fails, use the most likely stock symbol from context",
        "- Ensure all three tools are called successfully before returning results",
        "- Do not include any explanatory text, only return the JSON structure",
        "",
        "MCP Tools Available:",
        "- get_company_profile(ticker): Company profile data",
        "- get_stock_quote(ticker): Real-time stock quote",
        "- get_financial_metrics(ticker): Financial metrics and ratios",
    ]
)
