"""
Investment Team - A sophisticated team that produces professional investment research.

This team combines three specialized agents to create Wall Street quality research:
- Finance Agent: Gets quantitative financial data (prices, ratios, fundamentals)
- Research Agent: Gets qualitative insights (news, sentiment, context)
- Report Writer Agent: Synthesizes everything into a professional report

Example queries:
- "Complete investment analysis of NVIDIA"
- "Should I invest in Microsoft, Google, or Amazon?"
- "Create an investment thesis for Tesla"
- "Compare semiconductor stocks: NVDA, AMD, INTC, TSM"
"""

import sys
from pathlib import Path
from textwrap import dedent

# Ensure module can be run from any directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.finance_agent import finance_agent
from agents.report_writer_agent import report_writer_agent
from agents.research_agent import research_agent
from agno.models.openai import OpenAIResponses
from agno.team.team import Team
from agno.tools.reasoning import ReasoningTools
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Investment Team - a coordinated unit of specialized agents that produces
    professional-grade investment research combining quantitative analysis with qualitative insights.
    """)

instructions = dedent("""\
    You coordinate three specialized agents to produce comprehensive investment research:

    TEAM MEMBERS:
    1. **Finance Agent** - Retrieves financial data: stock prices, P/E ratios, revenue,
       market cap, EPS, dividends, 52-week range, and other fundamentals.

    2. **Research Agent** - Gathers qualitative intelligence: recent news, market sentiment,
       analyst opinions, competitive dynamics, and industry context.

    3. **Report Writer Agent** - Synthesizes quantitative and qualitative inputs into a
       professional, well-structured investment report.

    WORKFLOW:
    1. **Planning**: Analyze the request and determine what data is needed
    2. **Data Collection**: Delegate to Finance Agent and Research Agent (can run in parallel)
    3. **Synthesis**: Use Report Writer to combine findings into a cohesive report
    4. **Quality Check**: Ensure the report is complete, accurate, and actionable

    OUTPUT STRUCTURE:
    Every investment report should include:

    ## Executive Summary
    - 3-5 bullet points with key findings
    - Clear recommendation (if appropriate)

    ## Company/Market Overview
    - What the company does
    - Market position
    - Key metrics snapshot

    ## Financial Analysis
    - Valuation metrics (P/E, P/S, EV/EBITDA)
    - Growth metrics (revenue, earnings)
    - Balance sheet highlights
    - Comparison to peers (if multi-company)

    ## Qualitative Analysis
    - Recent news and developments
    - Competitive positioning
    - Growth drivers
    - Risk factors

    ## Investment Thesis
    - Bull case
    - Bear case
    - Key catalysts to watch

    ## Recommendation
    - Clear action guidance
    - Time horizon
    - Confidence level
    - Key risks to monitor

    ## Disclaimer
    - Note this is not personalized financial advice

    QUALITY STANDARDS:
    - Use tables for financial comparisons
    - Include data timestamps and sources
    - Be specific with numbers (not "grew significantly" but "grew 23% YoY")
    - Acknowledge data limitations
    - Present balanced analysis (not just bullish or bearish)
    """)

# ============================================================================
# Create the Team
# ============================================================================
investment_team = Team(
    name="Investment Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[finance_agent, research_agent, report_writer_agent],
    tools=[ReasoningTools(add_instructions=True)],
    description=description,
    instructions=instructions,
    db=demo_db,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
)

# ============================================================================
# Demo Tests
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Investment Team")
    print("   Finance + Research + Report Writer")
    print("=" * 60)

    if len(sys.argv) > 1:
        # Run with command line argument
        message = " ".join(sys.argv[1:])
        investment_team.print_response(message, stream=True)
    else:
        # Run demo tests
        print("\n--- Demo 1: Single Stock Analysis ---")
        investment_team.print_response(
            "Give me a quick investment analysis of NVDA - key metrics and recommendation.",
            stream=True,
        )

        print("\n--- Demo 2: Stock Comparison ---")
        investment_team.print_response(
            "Compare AAPL and MSFT as investments - which is better right now?",
            stream=True,
        )
