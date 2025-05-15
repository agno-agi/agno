# Example from the link:
#   https://docs.agno.com/examples/workflows/startup-idea-validator
#
# Putting everything in YAML file is better.
# But it will create more files in the public repo.
# For demonstrative purposes, load lib/agent.yml from PR #3054

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.utils.builder import agno
from pydantic import BaseModel, Field


class IdeaClarification(BaseModel):
    originality: str = Field(..., description="Originality of the idea.")
    mission: str = Field(..., description="Mission of the company.")
    objectives: str = Field(..., description="Objectives of the company.")


class MarketResearch(BaseModel):
    total_addressable_market: str = Field(
        ..., description="Total addressable market (TAM)."
    )
    serviceable_available_market: str = Field(
        ..., description="Serviceable available market (SAM)."
    )
    serviceable_obtainable_market: str = Field(
        ..., description="Serviceable obtainable market (SOM)."
    )
    target_customer_segments: str = Field(..., description="Target customer segments.")


idea_clarifier_agent: Agent = agno(
    "lib/agent",
    name="Idea Clarifier",
    model=DeepSeek(),
    instructions=[
        "Given a user's startup idea, its your goal to refine that idea. ",
        "Evaluates the originality of the idea by comparing it with existing concepts. ",
        "Define the mission and objectives of the startup.",
    ],
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    response_model=IdeaClarification,
    debug_mode=False,
)

market_research_agent: Agent = agno(
    "lib/agent",
    name="Market Researcher",
    model=DeepSeek(),
    tools=[agno('lib/tools', 'google')],
    instructions=[
        "You are provided with a startup idea and the company's mission and objectives. ",
        "Estimate the total addressable market (TAM), serviceable available market (SAM), and serviceable obtainable market (SOM). ",
        "Define target customer segments and their characteristics. ",
        "Search the web for resources if you need to.",
    ],
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    response_model=MarketResearch,
    debug_mode=False,
)

competitor_analysis_agent: Agent = agno(
    "lib/agent",
    name="Competitor Analysis",
    model=DeepSeek(),
    tools=[agno("lib/tools", "google")],
    instructions=[
        "You are provided with a startup idea and some market research related to the idea. ",
        "Identify existing competitors in the market. ",
        "Perform Strengths, Weaknesses, Opportunities, and Threats (SWOT) analysis for each competitor. ",
        "Assess the startup’s potential positioning relative to competitors.",
    ],
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    markdown=True,
    debug_mode=False,
)

report_agent: Agent = agno(
    "lib/agent",
    name="Report Generator",
    model=DeepSeek(),
    instructions=[
        "You are provided with a startup idea and other data about the idea. ",
        "Summarise everything into a single report.",
    ],
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    markdown=True,
    debug_mode=False,
)


# Run the workflow if the script is executed directly
if __name__ == "__main__":
    import json
    from rich.prompt import Prompt
    from rich.pretty import pprint

    # Get idea from user
    idea = Prompt.ask(
        "[bold]What is your startup idea?[/bold]\n✨",
        default="A marketplace for Christmas Ornaments made from leather",
    )

    workflow = (
        idea_clarifier_agent
        | market_research_agent
        | competitor_analysis_agent
        | report_agent
    )

    final_report = workflow.run_workflow(idea)

    pprint(json.loads(final_report.content))
