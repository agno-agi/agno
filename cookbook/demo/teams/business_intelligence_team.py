"""Business Intelligence Analyst Team - Multi-agent team for data analysis and business insights"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from pydantic import BaseModel, Field

from shared.database import db


class BusinessInsights(BaseModel):
    """Structured business intelligence report"""

    executive_summary: str = Field(description="High-level summary for executives")
    key_metrics: dict[str, float] = Field(description="Important KPIs and metrics")
    trends: list[str] = Field(description="Identified trends and patterns")
    opportunities: list[str] = Field(description="Business opportunities identified")
    risks: list[str] = Field(description="Potential risks or concerns")
    recommendations: list[str] = Field(description="Strategic recommendations")
    next_steps: list[str] = Field(description="Recommended action items")


data_analyst = Agent(
    name="Data Analyst",
    role="Analyzes data and identifies patterns",
    model=OpenAIChat(id="gpt-4o"),
    description="Expert data analyst specializing in statistical analysis and pattern recognition",
    instructions=[
        "Analyze business data for trends and patterns",
        "Calculate key metrics and KPIs",
        "Identify anomalies and outliers",
        "Perform statistical analysis",
        "Compare against benchmarks and historical data",
        "Provide data-driven insights",
        "Remember past analyses and historical trends",
        "Track key metrics over time",
    ],
    tools=[YFinanceTools(), DuckDuckGoTools()],
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=10,
    add_datetime_to_context=True,
    db=db,
    markdown=True,
)

insights_generator = Agent(
    name="Insights Generator",
    role="Translates data into business insights",
    model=Claude(id="claude-sonnet-4-20250514"),
    description="Business strategist who transforms data into actionable insights",
    instructions=[
        "Translate data findings into business implications",
        "Identify opportunities and risks",
        "Provide strategic recommendations",
        "Consider market context and competitive landscape",
        "Think about both short-term and long-term impact",
        "Prioritize insights by business value",
        "Remember past recommendations and their outcomes",
        "Track strategic trends and market shifts",
    ],
    tools=[DuckDuckGoTools()],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=8,
    add_datetime_to_context=True,
    db=db,
    markdown=True,
)

report_writer = Agent(
    name="Report Writer",
    role="Creates executive-level business reports",
    model=OpenAIChat(id="gpt-4o"),
    description="Specialist in creating clear, compelling business intelligence reports",
    instructions=[
        "Create executive-level summaries",
        "Present insights in clear, actionable format",
        "Use business-appropriate language and structure",
        "Highlight critical information",
        "Provide context and background",
        "Include specific recommendations and next steps",
        "Remember company reporting preferences and style",
        "Reference past reports for consistency",
    ],
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=5,
    db=db,
    output_schema=BusinessInsights,
    markdown=True,
)

bi_analyst_team = Team(
    id="bi-analyst-team",
    name="Business Intelligence Analyst Team",
    session_id="bi_analyst_session",
    model=OpenAIChat(id="gpt-4o"),
    members=[data_analyst, insights_generator, report_writer],
    db=db,
    description=dedent("""\
        AI-powered business intelligence team that analyzes data, identifies
        trends, generates insights, and creates executive-level reports with
        strategic recommendations. Features comprehensive memory to track historical
        data, past analyses, and company-specific metrics.\
    """),
    instructions=[
        "First, use Data Analyst to analyze the data and identify patterns",
        "Then, use Insights Generator to translate findings into business insights",
        "Finally, use Report Writer to create a comprehensive executive report",
        "Remember past analyses and reference historical trends",
        "Track key metrics and performance indicators over time",
        "Compare current data against historical benchmarks",
        "Focus on actionable insights and clear recommendations",
        "Consider both opportunities and risks",
        "Provide specific next steps prioritized by impact",
    ],
    show_members_responses=True,
    markdown=True,
)
