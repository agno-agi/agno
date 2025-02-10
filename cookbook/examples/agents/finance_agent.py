"""🗞️ Finance Agent - Your Personal Market Analyst!

This example shows how to create a sophisticated financial analyst that provides
comprehensive market insights using real-time data. The agent combines stock market data,
analyst recommendations, company information, and latest news to deliver professional-grade
financial analysis.

Example prompts to try:
- "What's the latest news and financial performance of Apple (AAPL)?"
- "Give me a detailed analysis of Tesla's (TSLA) current market position"
- "How are Microsoft's (MSFT) financials looking? Include analyst recommendations"
- "Analyze NVIDIA's (NVDA) stock performance and future outlook"
- "What's the market saying about Amazon's (AMZN) latest quarter?"

Run: `pip install openai yfinance agno` to install the dependencies
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools

finance_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            stock_fundamentals=True,
            historical_prices=True,
            company_info=True,
            company_news=True,
        )
    ],
    instructions=dedent("""\
        You are a seasoned Wall Street analyst with deep expertise in market analysis! 📊

        Follow these steps for comprehensive financial analysis:
        1. Market Overview
           - Latest stock price
           - 52-week high and low
        2. Financial Deep Dive
           - Key metrics (P/E, Market Cap, EPS)
        3. Professional Insights
           - Analyst recommendations breakdown
           - Recent rating changes

        4. Market Context
           - Industry trends and positioning
           - Competitive analysis
           - Market sentiment indicators

        Your reporting style:
        - Begin with an executive summary
        - Use tables for data presentation
        - Include clear section headers
        - Add emoji indicators for trends (📈 📉)
        - Highlight key insights with bullet points
        - Compare metrics to industry averages
        - Include technical term explanations
        - End with a forward-looking analysis

        Risk Disclosure:
        - Always highlight potential risk factors
        - Note market uncertainties
        - Mention relevant regulatory concerns
    """),
    add_datetime_to_instructions=True,
    show_tool_calls=True,
    markdown=True,
)

# Example usage with detailed market analysis request
finance_agent.print_response(
    "What's the latest news and financial performance of Apple (AAPL)?", stream=True
)

# Semiconductor market analysis example
finance_agent.print_response(
    dedent("""\
    Analyze the semiconductor market performance focusing on:
    - NVIDIA (NVDA)
    - AMD (AMD)
    - Intel (INTC)
    - Taiwan Semiconductor (TSM)
    Compare their market positions, growth metrics, and future outlook."""),
    stream=True,
)

# Automotive market analysis example
finance_agent.print_response(
    dedent("""\
    Evaluate the automotive industry's current state:
    - Tesla (TSLA)
    - Ford (F)
    - General Motors (GM)
    - Toyota (TM)
    Include EV transition progress and traditional auto metrics."""),
    stream=True,
)

# More example prompts to explore:
"""
Advanced analysis queries:
1. "Compare Tesla's valuation metrics with traditional automakers"
2. "Analyze the impact of recent product launches on AMD's stock performance"
3. "How do Meta's financial metrics compare to its social media peers?"
4. "Evaluate Netflix's subscriber growth impact on financial metrics"
5. "Break down Amazon's revenue streams and segment performance"

Industry-specific analyses:
Semiconductor Market:
1. "How is the chip shortage affecting TSMC's market position?"
2. "Compare NVIDIA's AI chip revenue growth with competitors"
3. "Analyze Intel's foundry strategy impact on stock performance"
4. "Evaluate semiconductor equipment makers like ASML and Applied Materials"

Automotive Industry:
1. "Compare EV manufacturers' production metrics and margins"
2. "Analyze traditional automakers' EV transition progress"
3. "How are rising interest rates impacting auto sales and stock performance?"
4. "Compare Tesla's profitability metrics with traditional auto manufacturers"
"""
