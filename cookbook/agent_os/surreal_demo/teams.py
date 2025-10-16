from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools
from agno.db.base import BaseDb


# ************* Core Agents *************


def get_reasoning_finance_team(db: BaseDb) -> Team:

    web_agent = Agent(
        name="Web Search Agent",
        role="Handle web search requests and general research",
        id="web_agent",
        model=OpenAIChat(id="gpt-4.1"),
        tools=[DuckDuckGoTools()],
        db=db,
        enable_user_memories=True,
        instructions=[
            "Search for current and relevant information on financial topics",
            "Always include sources and publication dates",
            "Focus on reputable financial news sources",
            "Provide context and background information",
        ],
        add_datetime_to_context=True,
    )

    finance_agent = Agent(
        name="Finance Agent",
        role="Handle financial data requests and market analysis",
        id="finance_agent",
        model=OpenAIChat(id="gpt-4.1"),
        tools=[YFinanceTools()],
        db=db,
        enable_user_memories=True,
        instructions=[
            "You are a financial data specialist and your goal is to generate comprehensive and accurate financial reports.",
            "Use tables to display stock prices, fundamentals (P/E, Market Cap, Revenue), and recommendations.",
            "Clearly state the company name and ticker symbol.",
            "Include key financial ratios and metrics in your analysis.",
            "Focus on delivering actionable financial insights.",
            "Delegate tasks and run tools in parallel if needed.",
        ],
        add_datetime_to_context=True,
    )
    # *******************************
    
    return Team(
    name="Reasoning Finance Team",
    id="reasoning_finance_team",
    model=Claude(id="claude-sonnet-4-0"),
    members=[
        web_agent,
        finance_agent,
    ],
    tools=[ReasoningTools(add_instructions=True)],
    instructions=[
        "Collaborate to provide comprehensive financial and investment insights",
        "Consider both fundamental analysis and market sentiment",
        "Provide actionable investment recommendations with clear rationale",
        "Use tables and charts to display data clearly and professionally",
        "Ensure all claims are supported by data and sources",
        "Present findings in a structured, easy-to-follow format",
        "Only output the final consolidated analysis, not individual agent responses",
        "Dont use emojis",
    ],
    db=db,
    enable_user_memories=True,
    markdown=True,
    show_members_responses=True,
    add_datetime_to_context=True,
)
