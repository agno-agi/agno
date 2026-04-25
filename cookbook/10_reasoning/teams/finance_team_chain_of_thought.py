"""
Finance Team Chain Of Thought
=============================

Demonstrates this reasoning cookbook example.
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.websearch import WebSearchTools


# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------
def run_example() -> None:
    web_agent = Agent(
        name="Web Search Agent",
        role="Handle web search requests",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[WebSearchTools()],
        instructions="Always include sources",
        add_datetime_to_context=True,
    )

    finance_agent = Agent(
        name="Finance Agent",
        role="Handle financial data requests",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[WebSearchTools(enable_news=False)],
        instructions=[
            "You are a financial data specialist. Provide concise and accurate data.",
            "Use tables to display stock prices, fundamentals (P/E, Market Cap), and recommendations.",
            "Clearly state the company name and ticker symbol.",
            "Briefly summarize recent company-specific news if available.",
            "Focus on delivering the requested financial data points clearly.",
        ],
        add_datetime_to_context=True,
    )

    team_leader = Team(
        name="Reasoning Finance Team Leader",
        members=[
            web_agent,
            finance_agent,
        ],
        instructions=[
            "Only output the final answer, no other text.",
            "Use tables to display data",
        ],
        markdown=True,
        reasoning=True,
        show_members_responses=True,
    )

    async def run_team(task: str):
        await team_leader.aprint_response(
            task,
            stream=True,
            show_full_reasoning=True,
        )

    if __name__ == "__main__":
        asyncio.run(
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
        )


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_example()
