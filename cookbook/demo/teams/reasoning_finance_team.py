from agno.agent import Agent
from agno.memory.v2.db.postgres import PostgresMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools

# ************* Database Connection *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
# *******************************

# ************* Memory *************
memory = Memory(
    model=OpenAIChat(id="gpt-4.1"),
    db=PostgresMemoryDb(table_name="user_memories", db_url=db_url),
    delete_memories=True,
    clear_memories=True,
)
# *******************************

# ************* Core Agents *************
web_agent = Agent(
    name="Web Search Agent",
    role="Handle web search requests and general research",
    agent_id="web_agent",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[DuckDuckGoTools()],
    storage=PostgresAgentStorage(
        db_url=db_url,
        table_name="web_agent_sessions",
    ),
    memory=memory,
    instructions=[
        "Search for current and relevant information on financial topics",
        "Always include sources and publication dates",
        "Focus on reputable financial news sources",
        "Provide context and background information",
    ],
    add_datetime_to_instructions=True,
)

finance_agent = Agent(
    name="Finance Agent",
    role="Handle financial data requests and market analysis",
    agent_id="finance_agent",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[
        YFinanceTools(
            stock_price=True,
            company_info=True,
            stock_fundamentals=True,
            key_financial_ratios=True,
            analyst_recommendations=True,
        )
    ],
    storage=PostgresAgentStorage(
        db_url=db_url,
        table_name="finance_agent_sessions",
    ),
    memory=memory,
    instructions=[
        "You are a financial data specialist and your goal is to generate comprehensive and accurate financial reports.",
        "Use tables to display stock prices, fundamentals (P/E, Market Cap, Revenue), and recommendations.",
        "Clearly state the company name and ticker symbol.",
        "Include key financial ratios and metrics in your analysis.",
        "Focus on delivering actionable financial insights.",
        "Delegate tasks and run tools in parallel if needed.",
    ],
    add_datetime_to_instructions=True,
)
# *******************************


def get_reasoning_finance_team():
    return Team(
        name="Reasoning Finance Team",
        mode="coordinate",
        team_id="reasoning_finance_team",
        model=Claude(id="claude-sonnet-4-20250514"),
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
        storage=PostgresAgentStorage(
            db_url=db_url,
            table_name="reasoning_finance_team_sessions",
        ),
        memory=memory,
        markdown=True,
        enable_agentic_memory=True,
        show_members_responses=True,
        enable_agentic_context=True,
        add_datetime_to_instructions=True,
        success_criteria="The team has provided a complete financial analysis with data, visualizations, risk assessment, and actionable investment recommendations supported by quantitative analysis and market research.",
    )


# ************* Demo Scenarios *************
"""
DEMO SCENARIOS - Use these as example queries to showcase the multi-agent system:

1. COMPREHENSIVE INVESTMENT RESEARCH:
Analyze Apple (AAPL) as a potential investment:
1. Get current stock price and fundamentals
2. Research recent news and market sentiment
3. Calculate key financial ratios and risk metrics
4. Provide a comprehensive investment recommendation

2. SECTOR COMPARISON ANALYSIS:
Compare the tech sector giants (AAPL, GOOGL, MSFT) performance:
1. Get financial data for all three companies
2. Analyze recent news affecting the tech sector
3. Calculate comparative metrics and correlations
4. Recommend portfolio allocation weights

3. RISK ASSESSMENT SCENARIO:
Evaluate the risk profile of Tesla (TSLA):
1. Calculate volatility metrics and beta
2. Analyze recent news for risk factors
3. Compare risk vs return to market benchmarks
4. Provide risk-adjusted investment recommendation

4. MARKET SENTIMENT ANALYSIS:
Analyze current market sentiment around AI stocks:
1. Search for recent AI industry news and developments
2. Get financial data for key AI companies (NVDA, GOOGL, MSFT, AMD)
3. Provide outlook for AI sector investing

5. EARNINGS SEASON ANALYSIS:
Prepare for upcoming earnings season - analyze Microsoft (MSFT):
1. Get current financial metrics and analyst expectations
2. Research recent news and market sentiment
3. Calculate historical earnings impact on stock price
4. Provide trading strategy recommendation
"""
# *******************************
