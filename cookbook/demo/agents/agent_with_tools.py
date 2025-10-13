"""Personal Finance Manager - AI agent for personalized financial advice and investment tracking"""

from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from pydantic import BaseModel, Field

from agno.db.sqlite.sqlite import SqliteDb

db = SqliteDb(id="real-world-db", db_file="tmp/real_world.db")


class FinancialAdvice(BaseModel):
    """Structured financial advice output"""

    summary: str = Field(description="Brief summary of financial advice")
    recommendations: list[str] = Field(description="Specific actionable recommendations")
    risk_level: str = Field(description="Risk assessment: low, medium, high")
    investment_allocation: Optional[dict[str, float]] = Field(
        default=None, description="Suggested portfolio allocation percentages"
    )
    next_steps: list[str] = Field(description="Immediate next steps to take")


personal_finance_agent = Agent(
    id="personal-finance-manager",
    name="Personal Finance Manager",
    session_id="finance_manager_session",
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
    db=db,
    description=dedent("""\
        Your personal AI financial advisor providing investment analysis,
        portfolio recommendations, budgeting advice, and financial planning
        guidance. Remembers your financial goals and preferences.\
    """),
    instructions=[
        "Provide personalized financial advice based on user's goals and risk tolerance",
        "Remember user's investment preferences and past decisions",
        "Use YFinance tools to get real-time market data",
        "Explain financial concepts in simple, accessible language",
        "Consider both short-term and long-term financial goals",
        "Provide balanced, risk-appropriate recommendations",
        "Include specific, actionable next steps",
        "Track portfolio performance over time",
        "Alert about significant market changes affecting user's holdings",
        "Always remind users that this is educational advice, not professional financial guidance",
    ],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=10,
    add_datetime_to_context=True,
    output_schema=FinancialAdvice,
    markdown=True,
)
