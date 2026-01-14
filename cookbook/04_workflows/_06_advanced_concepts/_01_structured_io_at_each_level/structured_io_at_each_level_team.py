from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field


# Define structured models for each step
class ResearchFindings(BaseModel):
    """Structured research findings with key insights"""

    topic: str = Field(description="The research topic")
    key_insights: List[str] = Field(description="Main insights discovered", min_items=3)
    trending_technologies: List[str] = Field(
        description="Technologies that are trending", min_items=2
    )
    market_impact: str = Field(description="Potential market impact analysis")
    sources_count: int = Field(description="Number of sources researched")
    confidence_score: float = Field(
        description="Confidence in findings (0.0-1.0)", ge=0.0, le=1.0
    )


class ContentStrategy(BaseModel):
    """Structured content strategy based on research"""

    target_audience: str = Field(description="Primary target audience")
    content_pillars: List[str] = Field(description="Main content themes", min_items=3)
    posting_schedule: List[str] = Field(description="Recommended posting schedule")
    key_messages: List[str] = Field(
        description="Core messages to communicate", min_items=3
    )
    hashtags: List[str] = Field(description="Recommended hashtags", min_items=5)
    engagement_tactics: List[str] = Field(
        description="Ways to increase engagement", min_items=2
    )


class FinalContentPlan(BaseModel):
    """Final content plan with specific deliverables"""

    campaign_name: str = Field(description="Name for the content campaign")
    content_calendar: List[str] = Field(
        description="Specific content pieces planned", min_items=6
    )
    success_metrics: List[str] = Field(
        description="How to measure success", min_items=3
    )
    budget_estimate: str = Field(description="Estimated budget range")
    timeline: str = Field(description="Implementation timeline")
    risk_factors: List[str] = Field(
        description="Potential risks and mitigation", min_items=2
    )


# Create individual agents for teams
research_specialist = Agent(
    name="Research Specialist",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    role="Find and analyze the latest AI trends and developments",
    instructions=[
        "Search for recent AI developments using available tools",
        "Focus on breakthrough technologies and market trends",
        "Provide detailed analysis with credible sources",
    ],
)

data_analyst = Agent(
    name="Data Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Analyze research data and extract key insights",
    instructions=[
        "Process research findings to identify patterns",
        "Quantify market impact and confidence levels",
        "Structure insights for strategic planning",
    ],
)

content_strategist = Agent(
    name="Content Strategist",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Develop content strategies based on research insights",
    instructions=[
        "Create comprehensive content strategies",
        "Focus on audience targeting and engagement",
        "Recommend optimal posting schedules and content pillars",
    ],
)

marketing_expert = Agent(
    name="Marketing Expert",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Provide marketing insights and hashtag recommendations",
    instructions=[
        "Suggest effective hashtags and engagement tactics",
        "Analyze target audience preferences",
        "Recommend proven marketing strategies",
    ],
)

project_manager = Agent(
    name="Project Manager",
    model=OpenAIChat(id="gpt-4o"),
    role="Create detailed project plans and timelines",
    instructions=[
        "Develop comprehensive implementation plans",
        "Set realistic timelines and budget estimates",
        "Identify potential risks and mitigation strategies",
    ],
)

budget_analyst = Agent(
    name="Budget Analyst",
    model=OpenAIChat(id="gpt-4o"),
    role="Analyze costs and provide budget recommendations",
    instructions=[
        "Estimate project costs and resource requirements",
        "Provide budget ranges and cost optimization suggestions",
        "Consider ROI and success metrics",
    ],
)

# Create teams with structured outputs
research_team = Team(
    name="AI Research Team",
    members=[research_specialist, data_analyst],
    delegate_to_all_members=True,
    model=OpenAIChat(id="gpt-4o"),
    description="A collaborative team that researches AI trends and extracts structured insights",
    output_schema=ResearchFindings,
    instructions=[
        "Work together to research the given topic thoroughly",
        "Combine research findings with data analysis",
        "Provide structured findings with confidence scores",
        "Focus on recent developments and market trends",
    ],
)

strategy_team = Team(
    name="Content Strategy Team",
    members=[content_strategist, marketing_expert],
    delegate_to_all_members=True,
    model=OpenAIChat(id="gpt-4o"),
    description="A strategic team that creates comprehensive content strategies",
    output_schema=ContentStrategy,
    instructions=[
        "Analyze the research findings from the previous step",
        "Collaborate to create a comprehensive content strategy",
        "Focus on audience engagement and brand building",
        "Combine content strategy with marketing expertise",
    ],
)

planning_team = Team(
    name="Content Planning Team",
    members=[project_manager, budget_analyst],
    delegate_to_all_members=True,
    model=OpenAIChat(id="gpt-4o"),
    description="A planning team that creates detailed implementation plans",
    output_schema=FinalContentPlan,
    instructions=[
        "Use the content strategy to create a detailed implementation plan",
        "Combine project management with budget analysis",
        "Include specific timelines and success metrics",
        "Consider budget and resource constraints",
    ],
)

# Define steps using teams
research_step = Step(
    name="Research Insights",
    team=research_team,  # Using team instead of agent
)

strategy_step = Step(
    name="Content Strategy",
    team=strategy_team,  # Using team instead of agent
)

planning_step = Step(
    name="Final Planning",
    team=planning_team,  # Using team instead of agent
)

# Create workflow with teams
structured_workflow = Workflow(
    name="Team-Based Structured Content Creation Pipeline",
    description="AI-powered content creation with teams and structured data flow",
    steps=[research_step, strategy_step, planning_step],
)

if __name__ == "__main__":
    print("=== Testing Structured Output Flow Between Teams ===")

    structured_workflow.print_response(
        input="Latest developments in artificial intelligence and machine learning",
    )
