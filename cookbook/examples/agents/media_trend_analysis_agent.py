"""Please install dependencies using:
pip install openai exa-py agno firecrawl
"""

from datetime import datetime, timedelta
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.exa import ExaTools
from agno.tools.firecrawl import FirecrawlTools


def calculate_start_date(days: int) -> str:
    """Calculate start date based on number of days."""
    start_date = datetime.now() - timedelta(days=days)
    return start_date.strftime("%Y-%m-%d")


agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ExaTools(start_published_date=calculate_start_date(30), type="keyword"),
        FirecrawlTools(scrape=True),
    ],
    description=dedent("""\
        You are an expert media trend analyst specializing in:
        1. Identifying emerging trends across news and digital platforms
        2. Recognizing pattern changes in media coverage
        3. Providing actionable insights based on data
        4. Forecasting potential future developments
    """),
    instructions=[
        "Analyze the provided topic according to the user's specifications:",
        "1. Use keywords to perform targeted searches",
        "2. Identify key influencers and authoritative sources",
        "3. Extract main themes and recurring patterns",
        "4. Provide actionable recommendations",
        "5. if got sources less then 2, only then scrape them using firecrawl tool, dont crawl it  and use them to generate the report",
        "6. growth rate should be in percentage , and if not possible dont give growth rate",
    ],
    expected_output=dedent("""\
    # Media Trend Analysis Report

    ## Executive Summary
    {High-level overview of findings and key metrics}

    ## Trend Analysis
    ### Volume Metrics
    - Peak discussion periods: {dates}
    - Growth rate: {percentage or dont show this}

    ## Source Analysis
    ### Top Sources
    1. {Source 1}

    2. {Source 2}


    ## Actionable Insights
    1. {Insight 1}
       - Evidence: {data points}
       - Recommended action: {action}

    ## Future Predictions
    1. {Prediction 1}
       - Supporting evidence: {evidence}

    ## References
    {Detailed source list with links}
    """),
    markdown=True,
    show_tool_calls=True,
    add_datetime_to_instructions=True,
)

# Example usage:
analysis_prompt = """\
Analyze media trends for:
Keywords: ai agents
Sources: verge.com ,linkedin.com, x.com
"""

agent.print_response(analysis_prompt, stream=True)

# Alternative prompt example
crypto_prompt = """\
Analyze media trends for:
Keywords: cryptocurrency, bitcoin, ethereum
Sources: coindesk.com, cointelegraph.com
"""

# agent.print_response(crypto_prompt, stream=True)
