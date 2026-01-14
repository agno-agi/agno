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


class AnalysisReport(BaseModel):
    """Enhanced analysis report with BaseModel output"""

    analysis_type: str = Field(description="Type of analysis performed")
    input_data_type: str = Field(description="Type of input data received")
    structured_data_detected: bool = Field(
        description="Whether structured data was found"
    )
    key_findings: List[str] = Field(description="Key findings from the analysis")
    recommendations: List[str] = Field(description="Recommendations for next steps")
    confidence_score: float = Field(
        description="Analysis confidence (0.0-1.0)", ge=0.0, le=1.0
    )
    data_quality_score: float = Field(
        description="Quality of input data (0.0-1.0)", ge=0.0, le=1.0
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


def enhanced_analysis_function(step_input: StepInput) -> StepOutput:
    """
    Enhanced custom function that returns a BaseModel instead of just a string.
    This demonstrates the new capability of StepOutput.content supporting structured data.
    """
    message = step_input.input
    previous_step_content = step_input.previous_step_content

    print("\n" + "=" * 60)
    print("🔍 ENHANCED CUSTOM FUNCTION WITH STRUCTURED OUTPUT")
    print("=" * 60)

    print(f"\n📝 Input Message Type: {type(message)}")
    print(f"📝 Input Message Value: {message}")

    print(f"\n📊 Previous Step Content Type: {type(previous_step_content)}")

    # Analysis results
    key_findings = []
    recommendations = []
    structured_data_detected = False
    confidence_score = 0.8
    data_quality_score = 0.9

    if previous_step_content:
        print("\n🔍 Previous Step Content Analysis:")

        if isinstance(previous_step_content, ResearchFindings):
            structured_data_detected = True
            print("✅ Detected ResearchFindings BaseModel")
            print(f"   Topic: {previous_step_content.topic}")
            print(
                f"   Key Insights: {len(previous_step_content.key_insights)} insights"
            )
            print(f"   Confidence: {previous_step_content.confidence_score}")

            # Extract findings from the structured data
            key_findings.extend(
                [
                    f"Research topic identified: {previous_step_content.topic}",
                    f"Found {len(previous_step_content.key_insights)} key insights",
                    f"Identified {len(previous_step_content.trending_technologies)} trending technologies",
                    f"Research confidence level: {previous_step_content.confidence_score}",
                    "Market impact assessment available",
                ]
            )

            recommendations.extend(
                [
                    "Leverage high-confidence research findings for content strategy",
                    "Focus on trending technologies identified in research",
                    "Use market impact insights for audience targeting",
                    "Build content around key insights with strong evidence",
                ]
            )

            confidence_score = previous_step_content.confidence_score
            data_quality_score = 0.95  # High quality due to structured input

        else:
            key_findings.append(
                "Received unstructured data - converted to string format"
            )
            recommendations.append(
                "Consider implementing structured data models for better processing"
            )
            confidence_score = 0.6
            data_quality_score = 0.7

    else:
        key_findings.append("No previous step content available")
        recommendations.append("Ensure data flow between steps is properly configured")
        confidence_score = 0.4
        data_quality_score = 0.5

    # Create structured analysis report using BaseModel
    analysis_report = AnalysisReport(
        analysis_type="Structured Data Flow Analysis",
        input_data_type=type(previous_step_content).__name__,
        structured_data_detected=structured_data_detected,
        key_findings=key_findings,
        recommendations=recommendations,
        confidence_score=confidence_score,
        data_quality_score=data_quality_score,
    )

    print("\n📋 Analysis Results (BaseModel):")
    print(f"   Analysis Type: {analysis_report.analysis_type}")
    print(f"   Structured Data: {analysis_report.structured_data_detected}")
    print(f"   Confidence: {analysis_report.confidence_score}")
    print(f"   Data Quality: {analysis_report.data_quality_score}")
    print("=" * 60)

    # Return StepOutput with BaseModel content
    return StepOutput(content=analysis_report, success=True)


def simple_data_processor(step_input: StepInput) -> StepOutput:
    """
    Simple function that demonstrates accessing different content types
    """
    print("\n🔧 SIMPLE DATA PROCESSOR")
    print(f"Previous step content type: {type(step_input.previous_step_content)}")

    # Access the structured data directly
    if isinstance(step_input.previous_step_content, AnalysisReport):
        report = step_input.previous_step_content
        print(f"Processing analysis report with confidence: {report.confidence_score}")

        summary = {
            "processor": "simple_data_processor",
            "input_confidence": report.confidence_score,
            "input_quality": report.data_quality_score,
            "processed_findings": len(report.key_findings),
            "processed_recommendations": len(report.recommendations),
            "status": "processed_successfully",
        }

        return StepOutput(content=summary, success=True)
    else:
        return StepOutput(
            content="Unable to process - expected AnalysisReport", success=False
        )


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

# Custom function step that returns a BaseModel
analysis_step = Step(
    name="enhanced_analysis",
    executor=enhanced_analysis_function,
)

# Another custom function that processes the BaseModel
processor_step = Step(
    name="data_processor",
    executor=simple_data_processor,
)

strategy_step = Step(
    name="content_strategy",
    agent=strategy_agent,
)

planning_step = Step(
    name="final_planning",
    agent=planning_agent,
)

# Create workflow with custom functions that demonstrate structured output
enhanced_workflow = Workflow(
    name="Enhanced Structured Content Creation Pipeline",
    description="AI-powered content creation with BaseModel outputs from custom functions",
    steps=[research_step, analysis_step, processor_step, strategy_step, planning_step],
)

if __name__ == "__main__":
    # Test with simple string input
    enhanced_workflow.print_response(
        input="Latest developments in artificial intelligence and machine learning",
        stream=True,
    )
