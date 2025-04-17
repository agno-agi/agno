from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

web_agent = Agent(
    name="Web Search Agent",
    role="Handle web search requests",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions="Always include sources",
    add_datetime_to_instructions=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Handle financial data requests",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        YFinanceTools(stock_price=True, analyst_recommendations=True, company_info=True)
    ],
    instructions=[
        "You are a financial data specialist. Provide concise and accurate data.",
        "Use tables to display stock prices, fundamentals (P/E, Market Cap), and recommendations.",
        "Clearly state the company name and ticker symbol.",
        "Briefly summarize recent company-specific news if available.",
        "Focus on delivering the requested financial data points clearly.",
    ],
    add_datetime_to_instructions=True,
)

team_leader = Team(
    name="Reasoning Finance Team Leader",
    mode="coordinate",
    model=Claude(id="claude-3-7-sonnet-latest"),
    members=[
        web_agent,
        finance_agent,
    ],
    tools=[ReasoningTools(add_instructions=True)],
    instructions=[
        "Only output the final answer, no other text.",
        "Use tables to display data",
    ],
    markdown=True,
    show_members_responses=True,
    enable_agentic_context=True,
    add_datetime_to_instructions=True,
    success_criteria="The team has successfully completed the task.",
)


def run_team(task: str):
    team_leader.print_response(
        task,
        stream=True,
        stream_intermediate_steps=True,
        show_full_reasoning=True,
    )


if __name__ == "__main__":
    run_team(
        dedent("""\
    Analyze the impact of recent US tariffs on market performance across these key sectors:
    - Steel & Aluminum: (X, NUE, AA)
    - Technology Hardware: (AAPL, DELL, HPQ)
    - Agricultural Products: (ADM, BG, INGR)
    - Automotive: (F, GM, TSLA)

    For each sector:
    1. Compare stock performance before and after tariff implementation
    2. Identify supply chain disruptions and cost impact percentages
    3. Analyze companies' strategic responses (reshoring, price adjustments, supplier diversification)
    4. Assess analyst outlook changes directly attributed to tariff policies
    """)
    )

    # run_team(dedent("""\
    # Assess the impact of recent semiconductor export controls on:
    # - US chip designers (Nvidia, AMD, Intel)
    # - Asian manufacturers (TSMC, Samsung)
    # - Equipment makers (ASML, Applied Materials)
    # Include effects on R&D investments, supply chain restructuring, and market share shifts."""))

    # run_team(dedent("""\
    # Compare the retail sector's response to consumer goods tariffs:
    # - Major retailers (Walmart, Target, Amazon)
    # - Consumer brands (Nike, Apple, Hasbro)
    # - Discount retailers (Dollar General, Five Below)
    # Include pricing strategy changes, inventory management, and consumer behavior impacts."""))

    # run_team(dedent("""\
    # Analyze the semiconductor market performance focusing on:
    # - NVIDIA (NVDA)
    # - AMD (AMD)
    # - Intel (INTC)
    # - Taiwan Semiconductor (TSM)
    # Compare their market positions, growth metrics, and future outlook."""))

    # run_team(dedent("""\
    # Evaluate the automotive industry's current state:
    # - Tesla (TSLA)
    # - Ford (F)
    # - General Motors (GM)
    # - Toyota (TM)
    # Include EV transition progress and traditional auto metrics."""))

    # run_team(dedent("""\
    # Compare the financial metrics of Apple (AAPL) and Google (GOOGL):
    # - Market Cap
    # - P/E Ratio
    # - Revenue Growth
    # - Profit Margin"""))

    # run_team(dedent("""\
    # Analyze the impact of recent Chinese solar panel tariffs on:
    # - US solar manufacturers (First Solar, SunPower)
    # - Chinese exporters (JinkoSolar, Trina Solar)
    # - US installation companies (Sunrun, SunPower)
    # Include effects on pricing, supply chains, and installation rates."""))
