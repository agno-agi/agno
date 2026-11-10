"""
Coordinate Mode with Structured Output

Demonstrates coordination that produces a Pydantic-validated structured response.
The team leader coordinates members and formats the final output to match a schema.

"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------


class CompanyBrief(BaseModel):
    company_name: str = Field(..., description="Name of the company")
    industry: str = Field(..., description="Primary industry")
    strengths: List[str] = Field(..., description="Key competitive strengths")
    risks: List[str] = Field(..., description="Notable risks or challenges")
    outlook: str = Field(..., description="Brief forward-looking assessment")


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

market_analyst = Agent(
    name="Market Analyst",
    role="Analyzes market position and competitive landscape",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You analyze companies from a market and competitive perspective.",
        "Focus on market share, competitors, and strategic positioning.",
    ],
)

risk_analyst = Agent(
    name="Risk Analyst",
    role="Identifies risks and challenges facing a company",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You identify and assess risks facing companies.",
        "Consider regulatory, financial, operational, and market risks.",
    ],
)

# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------

team = Team(
    name="Company Analysis Team",
    mode=TeamMode.coordinate,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[market_analyst, risk_analyst],
    instructions=[
        "You lead a company analysis team.",
        "Ask the Market Analyst for competitive analysis.",
        "Ask the Risk Analyst for risk assessment.",
        "Combine their insights into a structured company brief.",
    ],
    output_schema=CompanyBrief,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from rich.pretty import pprint

    response = team.run("Analyze Tesla as a company.")
    if response and isinstance(response.content, CompanyBrief):
        pprint(response.content.model_dump())
    elif response:
        print(response.content)
    else:
        print("No response")
