"""
Investment Memo Generator - Multi-Agent Financial Analysis System

Coordinates AI agents to analyze stocks, perform valuations, and generate investment memos.

Architecture:
- Company Profiler: Fetches real-time financial data via MCP
- Valuation Agent: Performs fundamental analysis and price targets
- Memo Writer: Generates executive investment recommendations
"""

import os
from dotenv import load_dotenv

load_dotenv()

from agno.os import AgentOS
from agno.team import Team
from agno.models.google import Gemini

# Import agents
from agents.company_profiler import CompanyProfiler
from agents.valuation_agent import ValuationAgent
from agents.memo_writer import MemoWriter

# Agent ecosystem
agents = [CompanyProfiler, ValuationAgent, MemoWriter]

# Investment research team
investment_research_team = Team(
    name="Investment Research Team",
    model=Gemini(id="gemini-2.0-flash", api_key=os.getenv("GEMINI_API_KEY")),
    members=[CompanyProfiler, ValuationAgent, MemoWriter],
    instructions=[
        "You coordinate an investment research team. Execute ALL steps sequentially:",
        "",
        "1. Ask Company Profiler to fetch real-time stock data (profile, quote, metrics)",
        "2. Pass ALL data to Valuation Agent for analysis",
        "3. Ask Memo Writer to create the investment memo using all the data",
        "",
        "CRITICAL: After Memo Writer responds, copy and return EXACTLY what Memo Writer outputs.",
        "DO NOT summarize, DO NOT add your own text, DO NOT say 'undefined'.",
        "Simply return the complete markdown memo from Memo Writer as-is.",
    ],
    markdown=True,
    show_members_responses=True,
)

# Initialize AgentOS
agent_os = AgentOS(
    name="Investment Memo Generator for Analyst Teams",
    description="AI-powered investment research and memo generation using collaborative agent teams with MCP",
    agents=agents,
    teams=[investment_research_team],
)

# FastAPI app
app = agent_os.get_app()

# Launch server
if __name__ == "__main__":
    agent_os.serve(app="main:app", host="localhost", port=7777, reload=False)
