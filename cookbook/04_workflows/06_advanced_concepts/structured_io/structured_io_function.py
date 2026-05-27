"""
Structured IO Function
======================

Demonstrates custom function steps in structured workflows, including string and BaseModel outputs.
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.hackernews import HackerNewsTools
from agno.tools.websearch import WebSearchTools
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Define Structured Models
# ---------------------------------------------------------------------------
class ResearchFindings(BaseModel):
    topic: str = Field(description="The research topic")
    key_insights: List[str] = Field(description="Main insights discovered", min_items=3)
    trending_technologies: List[str] = Field(
        description="Technologies that are trending",
        min_items=2,
    )
    market_impact: str = Field(description="Potential market impact analysis")
    sources_count: int = Field(description="Number of sources researched")
    confidence_score: float = Field(
        description="Confidence in findings (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )


class ContentStrategy(BaseModel):
    target_audience: str = Field(description="Primary target audience")
    content_pillars: List[str] = Field(description="Main content themes", min_items=3)
    posting_schedule: List[str] = Field(description="Recommended posting schedule")
    key_messages: List[str] = Field(
        description="Core messages to communicate",
        min_items=3,
    )
    hashtags: List[str] = Field(description="Recommended hashtags", min_items=5)
    engagement_tactics: List[str] = Field(
        description="Ways to increase engagement",
        min_items=2,
    )


class AnalysisReport(BaseModel):
    analysis_type: str = Field(description="Type of analysis performed")
    input_data_type: str = Field(description="Type of input data received")
    structured_data_detected: bool = Field(
        description="Whether structured data was found"
    )
    key_findings: List[str] = Field(description="Key findings from the analysis")
    recommendations: List[str] = Field(description="Recommendations for next steps")
    confidence_score: float = Field(
        description="Analysis confidence (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )
    data_quality_score: float = Field(
        description="Quality of input data (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )


class FinalContentPlan(BaseModel):
    campaign_name: str = Field(description="Name for the content campaign")
    content_calendar: List[str] = Field(
        description="Specific content pieces planned",
        min_items=6,
    )
    success_metrics: List[str] = Field(
        description="How to measure success",
        min_items=3,
    )
    budget_estimate: str = Field(description="Estimated budget range")
    timeline: str = Field(description="Implementation timeline")
    risk_factors: List[str] = Field(
        description="Potential risks and mitigation",
        min_items=2,
    )


# ---------------------------------------------------------------------------
# Define Function Executors
# ---------------------------------------------------------------------------
def data_analysis_function(step_input: StepInput) -> StepOutput:
    message = step_input.input
    previous_step_content = step_input.previous_step_content

    print("\n" + "=" * 60)
    print("CUSTOM FUNCTION DATA ANALYSIS")
    print("=" * 60)

    print(f"\nInput Message Type: {type(message)}")
    print(f"Input Message Value: {message}")

    print(f"\nPrevious Step Content Type: {type(previous_step_content)}")

    analysis_results = []

    if previous_step_content:
        print("\nPrevious Step Content Preview:")
        print("Topic: ", previous_step_content.topic, "\n")
        print("Key Insights: ", previous_step_content.key_insights, "\n")
        print(
            "Trending Technologies: ", previous_step_content.trending_technologies, "\n"
        )

        analysis_results.append("[PASS] Received structured data (BaseModel)")
        analysis_results.append(
            f"[PASS] BaseModel type: {type(previous_step_content).__name__}"
        )
        try:
            model_dict = previous_step_content.model_dump()
            analysis_results.append(f"[PASS] Model fields: {list(model_dict.keys())}")

            if hasattr(previous_step_content, "topic"):
                analysis_results.append(
                    f"[PASS] Research Topic: {previous_step_content.topic}"
                )
            if hasattr(previous_step_content, "confidence_score"):
                analysis_results.append(
                    f"[PASS] Confidence Score: {previous_step_content.confidence_score}"
                )
        except Exception as e:
            analysis_results.append(f"[FAIL] Error accessing BaseModel: {e}")

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

    print("\nAnalysis Results:")
    for result in analysis_results:
        print(f"   {result}")

    print("=" * 60)

    return StepOutput(content=enhanced_analysis, success=True)


def enhanced_analysis_function(step_input: StepInput) -> StepOutput:
    message = step_input.input
    previous_step_content = step_input.previous_step_content

    print("\n" + "=" * 60)
    print("ENHANCED CUSTOM FUNCTION WITH STRUCTURED OUTPUT")
    print("=" * 60)

    print(f"\nInput Message Type: {type(message)}")
    print(f"Input Message Value: {message}")
    print(f"\nPrevious Step Content Type: {type(previous_step_content)}")

    key_findings = []
    recommendations = []
    structured_data_detected = False
    confidence_score = 0.8
    data_quality_score = 0.9

    if previous_step_content:
        print("\nPrevious Step Content Analysis:")

        if isinstance(previous_step_content, ResearchFindings):
            structured_data_detected = True
            print("[PASS] Detected ResearchFindings BaseModel")
            print(f"   Topic: {previous_step_content.topic}")
            print(
                f"   Key Insights: {len(previous_step_content.key_insights)} insights"
            )
            print(f"   Confidence: {previous_step_content.confidence_score}")

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
            data_quality_score = 0.95

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

    analysis_report = AnalysisReport(
        analysis_type="Structured Data Flow Analysis",
        input_data_type=type(previous_step_content).__name__,
        structured_data_detected=structured_data_detected,
        key_findings=key_findings,
        recommendations=recommendations,
        confidence_score=confidence_score,
        data_quality_score=data_quality_score,
    )

    print("\nAnalysis Results (BaseModel):")
    print(f"   Analysis Type: {analysis_report.analysis_type}")
    print(f"   Structured Data: {analysis_report.structured_data_detected}")
    print(f"   Confidence: {analysis_report.confidence_score}")
    print(f"   Data Quality: {analysis_report.data_quality_score}")
    print("=" * 60)

    return StepOutput(content=analysis_report, success=True)


def simple_data_processor(step_input: StepInput) -> StepOutput:
    print("\nSIMPLE DATA PROCESSOR")
    print(f"Previous step content type: {type(step_input.previous_step_content)}")

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

    return StepOutput(
        content="Unable to process - expected AnalysisReport", success=False
    )


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
research_agent = Agent(
    name="AI Research Specialist",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools(), WebSearchTools()],
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

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_step = Step(
    name="research_insights",
    agent=research_agent,
)

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

enhanced_analysis_step = Step(
    name="enhanced_analysis",
    executor=enhanced_analysis_function,
)

processor_step = Step(
    name="data_processor",
    executor=simple_data_processor,
)

# ---------------------------------------------------------------------------
# Create Workflows
# ---------------------------------------------------------------------------
structured_workflow = Workflow(
    name="Structured Content Creation Pipeline with Analysis",
    description="AI-powered content creation with data flow analysis",
    steps=[research_step, analysis_step, strategy_step, planning_step],
)

enhanced_workflow = Workflow(
    name="Enhanced Structured Content Creation Pipeline",
    description="AI-powered content creation with BaseModel outputs from custom functions",
    steps=[
        research_step,
        enhanced_analysis_step,
        processor_step,
        strategy_step,
        planning_step,
    ],
)

# ---------------------------------------------------------------------------
# Run Workflows
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Testing Structured Output Flow with Custom Function Analysis ===")
    structured_workflow.print_response(
        input="Latest developments in artificial intelligence and machine learning",
    )

    print("\n=== Testing Enhanced Structured Output from Custom Function ===")
    enhanced_workflow.print_response(
        input="Latest developments in artificial intelligence and machine learning",
        stream=True,
    )
