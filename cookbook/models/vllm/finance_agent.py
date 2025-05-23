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
from agno.models.vllm import vLLMOpenAI
from agno.tools.yfinance import YFinanceTools

finance_agent = Agent(
    model=vLLMOpenAI(
        id="NousResearch/Nous-Hermes-2-Mistral-7B-DPO", top_k=20, enable_thinking=False
    ),
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
    instructions=dedent(
        """\
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
    """
    ),
    add_datetime_to_instructions=True,
    markdown=True,
)

# Example usage with detailed market analysis request
finance_agent.print_response(
    "Write a comprehensive report on TSLA",
    stream=True,
    stream_intermediate_steps=True,
)
