from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.step import Step, StepInput, StepOutput
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


def data_analysis_function(step_input: StepInput) -> StepOutput:
    """
    Custom function to analyze the structured data received from previous step
    This will help us see what format the data is in when received
    """
    message = step_input.input
    previous_step_content = step_input.previous_step_content

    print("\n" + "=" * 60)
    print("🔍 CUSTOM FUNCTION DATA ANALYSIS")
    print("=" * 60)

    print(f"\n📝 Input Message Type: {type(message)}")
    print(f"📝 Input Message Value: {message}")

    print(f"\n📊 Previous Step Content Type: {type(previous_step_content)}")

    # Try to parse if it's structured data
    analysis_results = []

    if previous_step_content:
        print("\n🔍 Previous Step Content Preview:")
        print("Topic: ", previous_step_content.topic, "\n")
        print("Key Insights: ", previous_step_content.key_insights, "\n")
        print(
            "Trending Technologies: ", previous_step_content.trending_technologies, "\n"
        )

        analysis_results.append("✅ Received structured data (BaseModel)")

        # If it's a BaseModel, try to access its fields
        analysis_results.append(
            f"✅ BaseModel type: {type(previous_step_content).__name__}"
        )
        try:
            model_dict = previous_step_content.model_dump()
            analysis_results.append(f"✅ Model fields: {list(model_dict.keys())}")

            # If it's ResearchFindings, extract specific data
            if hasattr(previous_step_content, "topic"):
                analysis_results.append(
                    f"✅ Research Topic: {previous_step_content.topic}"
                )
            if hasattr(previous_step_content, "confidence_score"):
                analysis_results.append(
                    f"✅ Confidence Score: {previous_step_content.confidence_score}"
                )

        except Exception as e:
            analysis_results.append(f"❌ Error accessing BaseModel: {e}")

    # Create enhanced analysis
    enhanced_analysis = f"""
        ## Data Flow Analysis Report

        **Input Analysis:**
        - Message Type: {type(message).__name__}
        - Previous Content Type: {type(previous_step_content).__name__}

        **Structure Analysis:**
        {chr(10).join(analysis_results)}

        **Recommendations for Next Step:**
        Based on the data analysis, the content planning step should receive this processed information.
    """.strip()

    print("\n📋 Analysis Results:")
    for result in analysis_results:
        print(f"   {result}")

    print("=" * 60)

    return StepOutput(content=enhanced_analysis, success=True)


# Define agents with response models
research_agent = Agent(
    name="AI Research Specialist",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools(), DuckDuckGoTools()],
    role="Research AI trends and extract structured insights",
    output_schema=ResearchFindings,
    instructions=[
        "Research the given topic thoroughly using available tools",
        "Provide structured findings with confidence scores",
        "Focus on recent developments and market trends",
        "Make sure to structure your response according to the ResearchFindings model",
    ],
)

strategy_agent = Agent(
    name="Content Strategy Expert",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Create content strategies based on research findings",
    output_schema=ContentStrategy,
    instructions=[
        "Analyze the research findings provided from the previous step",
        "Create a comprehensive content strategy based on the structured research data",
        "Focus on audience engagement and brand building",
        "Structure your response according to the ContentStrategy model",
    ],
)

planning_agent = Agent(
    name="Content Planning Specialist",
    model=OpenAIChat(id="gpt-4o"),
    role="Create detailed content plans and calendars",
    output_schema=FinalContentPlan,
    instructions=[
        "Use the content strategy from the previous step to create a detailed implementation plan",
        "Include specific timelines and success metrics",
        "Consider budget and resource constraints",
        "Structure your response according to the FinalContentPlan model",
    ],
)

# Define steps
research_step = Step(
    name="research_insights",
    agent=research_agent,
)

# Custom function step to analyze data flow
analysis_step = Step(
    name="data_analysis",
    executor=data_analysis_function,
)

strategy_step = Step(
    name="content_strategy",
    agent=strategy_agent,
)

planning_step = Step(
    name="final_planning",
    agent=planning_agent,
)

# Create workflow with custom function in between
structured_workflow = Workflow(
    name="Structured Content Creation Pipeline with Analysis",
    description="AI-powered content creation with data flow analysis",
    steps=[research_step, analysis_step, strategy_step, planning_step],
)

if __name__ == "__main__":
    print("=== Testing Structured Output Flow with Custom Function Analysis ===")

    # Test with simple string input
    structured_workflow.print_response(
        input="Latest developments in artificial intelligence and machine learning",
        # stream=True,
    )
