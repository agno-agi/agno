import json
from datetime import datetime
from typing import AsyncIterator, List, Union

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.run import RunContext
from agno.run.workflow import WorkflowRunOutputEvent
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field


# Define structured output models for each research phase
class CustomerProfileResearch(BaseModel):
    """Structured customer profile research findings"""

    research_topic: str = Field(description="The customer research topic")
    target_demographics: List[str] = Field(
        description="Key demographic segments identified", min_items=2
    )
    customer_personas: List[str] = Field(
        description="Defined customer personas", min_items=2
    )
    pain_points: List[str] = Field(
        description="Major customer pain points discovered", min_items=3
    )
    motivations: List[str] = Field(
        description="Customer motivations and drivers", min_items=3
    )
    customer_journey: List[str] = Field(
        description="Key touchpoints in customer journey", min_items=3
    )
    behavioral_patterns: List[str] = Field(
        description="Customer behavioral insights", min_items=2
    )
    segmentation_insights: str = Field(description="Customer segmentation summary")
    confidence_score: float = Field(
        description="Confidence in findings (0.0-1.0)", ge=0.0, le=1.0
    )


class BusinessGoalsResearch(BaseModel):
    """Structured business goals research findings"""

    research_topic: str = Field(description="The business goals research topic")
    primary_objectives: List[str] = Field(
        description="Main business objectives identified", min_items=3
    )
    key_metrics: List[str] = Field(
        description="Important KPIs and success metrics", min_items=3
    )
    industry_trends: List[str] = Field(
        description="Relevant industry trends", min_items=3
    )
    competitive_landscape: List[str] = Field(
        description="Competitive analysis insights", min_items=2
    )
    growth_opportunities: List[str] = Field(
        description="Identified growth opportunities", min_items=2
    )
    strategic_challenges: List[str] = Field(
        description="Key challenges to address", min_items=2
    )
    market_positioning: str = Field(description="Market positioning analysis")
    success_factors: List[str] = Field(
        description="Critical success factors", min_items=2
    )
    confidence_score: float = Field(
        description="Confidence in findings (0.0-1.0)", ge=0.0, le=1.0
    )


class WebIntelligenceResearch(BaseModel):
    """Structured web intelligence research findings"""

    research_topic: str = Field(description="The web intelligence research topic")
    digital_presence: List[str] = Field(
        description="Digital presence insights", min_items=2
    )
    social_media_patterns: List[str] = Field(
        description="Social media engagement patterns", min_items=2
    )
    web_behavior: List[str] = Field(description="Web behavior analysis", min_items=2)
    digital_touchpoints: List[str] = Field(
        description="Key digital touchpoints", min_items=3
    )
    online_positioning: List[str] = Field(
        description="Online brand positioning insights", min_items=2
    )
    digital_marketing: List[str] = Field(
        description="Digital marketing strategies observed", min_items=2
    )
    engagement_metrics: str = Field(
        description="Engagement and interaction patterns summary"
    )
    technology_stack: List[str] = Field(
        description="Technology platforms and tools identified", min_items=2
    )
    confidence_score: float = Field(
        description="Confidence in findings (0.0-1.0)", ge=0.0, le=1.0
    )


class ConsolidatedResearch(BaseModel):
    """Consolidated research findings from all phases"""

    research_query: str = Field(description="Original research query")
    key_insights: List[str] = Field(
        description="Top consolidated insights", min_items=5
    )
    customer_profile_summary: str = Field(
        description="Executive summary of customer profile"
    )
    business_goals_summary: str = Field(
        description="Executive summary of business goals"
    )
    web_intelligence_summary: str = Field(
        description="Executive summary of web intelligence"
    )
    strategic_opportunities: List[str] = Field(
        description="Strategic opportunities identified", min_items=3
    )
    critical_findings: List[str] = Field(
        description="Most critical findings across all research", min_items=4
    )
    patterns_correlations: List[str] = Field(
        description="Patterns and correlations found", min_items=2
    )
    recommendations: List[str] = Field(
        description="High-level recommendations", min_items=3
    )
    research_confidence: float = Field(
        description="Overall research confidence (0.0-1.0)", ge=0.0, le=1.0
    )


# Define specialized research agents
customer_profile_agent = Agent(
    name="Customer Profile Researcher",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    output_schema=CustomerProfileResearch,
    instructions=[
        "You are an expert customer profile researcher specializing in comprehensive customer analysis",
        "Research customer demographics, psychographics, and behavioral patterns using available tools",
        "Focus on understanding customer personas, pain points, and motivations",
        "Analyze customer journey touchpoints and behavioral insights",
        "Provide structured findings according to the CustomerProfileResearch model",
        "Include confidence scores and detailed segmentation insights",
        "Use tools extensively to gather data-driven insights",
    ],
    db=InMemoryDb(),
)

business_goals_agent = Agent(
    name="Business Goals Researcher",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(), HackerNewsTools()],
    output_schema=BusinessGoalsResearch,
    instructions=[
        "You are a business strategy and goals research specialist with deep market expertise",
        "Analyze customer business objectives, KPIs, and success metrics using available tools",
        "Research industry trends, competitive landscape, and market opportunities",
        "Identify growth opportunities and strategic challenges",
        "Focus on understanding what customers want to achieve and critical success factors",
        "Provide structured findings according to the BusinessGoalsResearch model",
        "Include confidence scores and comprehensive market positioning analysis",
        "Use tools to gather current industry data and competitive intelligence",
    ],
    db=InMemoryDb(),
)

web_intelligence_agent = Agent(
    name="Web Intelligence Researcher",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(), HackerNewsTools()],
    output_schema=WebIntelligenceResearch,
    instructions=[
        "You are a web intelligence and market research specialist with expertise in digital analytics",
        "Research customer's online presence, digital footprint, and web behavior using available tools",
        "Analyze social media presence, website activity, and digital engagement patterns",
        "Identify digital touchpoints, technology stacks, and online positioning strategies",
        "Provide insights on customer's digital marketing approaches and engagement metrics",
        "Structure your findings according to the WebIntelligenceResearch model",
        "Include confidence scores and comprehensive engagement analysis",
        "Use tools to gather current digital presence and online behavior data",
    ],
    db=InMemoryDb(),
)

# Create research team for consolidation
research_consolidation_team = Team(
    name="Research Consolidation Team",
    members=[customer_profile_agent, business_goals_agent, web_intelligence_agent],
    output_schema=ConsolidatedResearch,
    instructions=[
        "You are a research consolidation team specializing in synthesizing complex research data",
        "Synthesize all research findings into comprehensive customer insights and patterns",
        "Identify correlations, patterns, and key insights across customer profile, business goals, and web intelligence research",
        "Create actionable recommendations and strategic opportunities based on consolidated research",
        "Analyze critical findings and provide executive summaries for each research phase",
        "Structure your consolidated findings according to the ConsolidatedResearch model",
        "Include overall research confidence and strategic recommendations",
        "Focus on creating cohesive insights that integrate all research phases",
    ],
    db=InMemoryDb(),
)

# Task recommender agent
task_recommender_agent = Agent(
    name="Task Recommender",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are an expert task and strategy recommender with deep implementation expertise",
        "Based on consolidated customer research, provide specific, actionable tasks and recommendations",
        "Prioritize tasks based on impact, urgency, and feasibility assessment",
        "Create detailed action plans with implementation timelines and success metrics",
        "Identify quick wins, resource requirements, and risk mitigation strategies",
        "Develop both high and medium priority task categories with long-term strategic initiatives",
        "Structure your recommendations according to the TaskRecommendations model",
        "Include feasibility assessment and comprehensive implementation guidance",
    ],
    db=InMemoryDb(),
)


def set_session_state_step(
    step_input: StepInput, run_context: RunContext
) -> StepOutput:
    """
    Initialize session state for customer research workflow
    """
    customer_query = step_input.input

    if run_context.session_state is None:
        run_context.session_state = {}

    # Initialize comprehensive session state structure
    if "customer_research" not in run_context.session_state:
        run_context.session_state["customer_research"] = {
            "workflow_id": f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "customer_query": str(customer_query),
            "research_phases": {
                "profile": {"status": "pending", "findings": []},
                "business_goals": {"status": "pending", "findings": []},
                "web_intelligence": {"status": "pending", "findings": []},
            },
            "consolidated_insights": [],
            "recommendations": [],
            "research_metadata": {
                "started_at": datetime.now().isoformat(),
                "total_research_steps": 0,
                "completed_steps": 0,
            },
        }

    # Set workflow configuration
    run_context.session_state["workflow_config"] = {
        "research_depth": "comprehensive",
        "focus_areas": ["customer_profile", "business_goals", "web_intelligence"],
        "output_format": "detailed_report",
        "created_by": "customer_research_team",
    }

    # Set research preferences
    run_context.session_state["research_preferences"] = {
        "analysis_style": "data_driven",
        "recommendation_type": "actionable_tasks",
        "reporting_level": "executive_summary",
    }

    run_context.session_state["customer_research"]["research_metadata"][
        "total_research_steps"
    ] += 1

    return StepOutput(
        content=f"""
        ## Customer Research Session Initialized

        **Research Query:** {customer_query}
        **Workflow ID:** {run_context.session_state["customer_research"]["workflow_id"]}
        **Research Phases:** {len(run_context.session_state["customer_research"]["research_phases"])} phases planned

        **Session Configuration:**
        - Research Depth: {run_context.session_state["workflow_config"]["research_depth"]}
        - Focus Areas: {", ".join(run_context.session_state["workflow_config"]["focus_areas"])}
        - Analysis Style: {run_context.session_state["research_preferences"]["analysis_style"]}

        Session state has been initialized and is ready for comprehensive customer research.
        """.strip()
    )


async def customer_profile_research_step(
    step_input: StepInput, session_state: dict
) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
    """
    Conduct customer profile research with session state tracking
    """
    customer_query = step_input.input
    previous_content = step_input.previous_step_content

    # Update session state
    session_state["customer_research"]["research_phases"]["profile"]["status"] = (
        "in_progress"
    )

    research_prompt = f"""
    CUSTOMER PROFILE RESEARCH REQUEST:

    Research Query: {customer_query}
    Session Context: {session_state["customer_research"]["workflow_id"]}
    Previous Context: {previous_content[:300] if previous_content else "Initial research"}

    RESEARCH OBJECTIVES:
    1. Identify target customer demographics and psychographics
    2. Understand customer personas and segmentation
    3. Analyze customer pain points and motivations
    4. Research customer journey and touchpoints
    5. Identify customer preferences and behaviors

    Provide comprehensive customer profile insights with specific data points and actionable findings.
    """

    try:
        research_result_iterator = customer_profile_agent.arun(
            research_prompt, stream=True, stream_events=True
        )

        async for event in research_result_iterator:
            yield event

        # Get the actual response after streaming
        research_result = customer_profile_agent.get_last_run_output()

        # Store findings in session state with structured data
        findings = {
            "research_type": "customer_profile",
            "timestamp": datetime.now().isoformat(),
            "structured_data": research_result.content,
            "success": True,
        }

        session_state["customer_research"]["research_phases"]["profile"][
            "findings"
        ].append(findings)
        session_state["customer_research"]["research_phases"]["profile"]["status"] = (
            "completed"
        )
        session_state["customer_research"]["research_metadata"]["completed_steps"] += 1

        # Return the structured Pydantic data directly
        yield StepOutput(content=research_result.content, success=True)

    except Exception as e:
        session_state["customer_research"]["research_phases"]["profile"]["status"] = (
            "failed"
        )
        yield StepOutput(
            content=f"Customer profile research failed: {str(e)}", success=False
        )


async def customer_biz_goals_research_step(
    step_input: StepInput, session_state: dict
) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
    """
    Conduct business goals research with session state tracking
    """
    customer_query = step_input.input

    # Update session state
    session_state["customer_research"]["research_phases"]["business_goals"][
        "status"
    ] = "in_progress"

    research_prompt = f"""
    CUSTOMER BUSINESS GOALS RESEARCH REQUEST:

    Research Query: {customer_query}
    Session Context: {session_state["customer_research"]["workflow_id"]}
    Research Depth: {session_state["workflow_config"]["research_depth"]}

    RESEARCH OBJECTIVES:
    1. Identify customer's primary business objectives and KPIs
    2. Understand success metrics and performance indicators
    3. Analyze industry trends affecting customer goals
    4. Research competitive landscape and market positioning
    5. Identify growth opportunities and challenges

    Provide detailed business goals analysis with strategic insights and market context.
    """

    try:
        research_result_iterator = business_goals_agent.arun(
            research_prompt, stream=True, stream_events=True
        )

        async for event in research_result_iterator:
            yield event

        # Get the actual response after streaming
        research_result = business_goals_agent.get_last_run_output()

        # Store findings in session state with structured data
        findings = {
            "research_type": "business_goals",
            "timestamp": datetime.now().isoformat(),
            "structured_data": research_result.content,
            "success": True,
        }

        session_state["customer_research"]["research_phases"]["business_goals"][
            "findings"
        ].append(findings)
        session_state["customer_research"]["research_phases"]["business_goals"][
            "status"
        ] = "completed"
        session_state["customer_research"]["research_metadata"]["completed_steps"] += 1

        # Return the structured Pydantic data directly
        yield StepOutput(content=research_result.content, success=True)

    except Exception as e:
        session_state["customer_research"]["research_phases"]["business_goals"][
            "status"
        ] = "failed"
        yield StepOutput(
            content=f"Business goals research failed: {str(e)}", success=False
        )


async def web_intelligence_research_step(
    step_input: StepInput, session_state: dict
) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
    """
    Conduct web intelligence research with session state tracking
    """
    customer_query = step_input.input

    # Update session state
    session_state["customer_research"]["research_phases"]["web_intelligence"][
        "status"
    ] = "in_progress"

    research_prompt = f"""
    WEB INTELLIGENCE RESEARCH REQUEST:

    Research Query: {customer_query}
    Session Context: {session_state["customer_research"]["workflow_id"]}
    Analysis Style: {session_state["research_preferences"]["analysis_style"]}

    RESEARCH OBJECTIVES:
    1. Analyze customer's digital presence and online footprint
    2. Research social media activity and engagement patterns
    3. Understand web behavior and digital touchpoints
    4. Identify online brand positioning and messaging
    5. Analyze digital marketing strategies and channels

    Provide comprehensive web intelligence with digital insights and online behavior analysis.
    """

    try:
        research_result_iterator = web_intelligence_agent.arun(
            research_prompt, stream=True, stream_events=True
        )

        async for event in research_result_iterator:
            yield event

        # Get the actual response after streaming
        research_result = web_intelligence_agent.get_last_run_output()

        # Store findings in session state with structured data
        findings = {
            "research_type": "web_intelligence",
            "timestamp": datetime.now().isoformat(),
            "structured_data": research_result.content,
            "success": True,
        }

        session_state["customer_research"]["research_phases"]["web_intelligence"][
            "findings"
        ].append(findings)
        session_state["customer_research"]["research_phases"]["web_intelligence"][
            "status"
        ] = "completed"
        session_state["customer_research"]["research_metadata"]["completed_steps"] += 1

        # Return the structured Pydantic data directly
        yield StepOutput(content=research_result.content, success=True)

    except Exception as e:
        session_state["customer_research"]["research_phases"]["web_intelligence"][
            "status"
        ] = "failed"
        yield StepOutput(
            content=f"Web intelligence research failed: {str(e)}", success=False
        )


async def customer_report_consolidation_step(
    step_input: StepInput, session_state: dict
) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
    """
    Consolidate all research findings into comprehensive customer report
    """
    customer_query = step_input.input

    # Gather all research findings from session state
    research_data = session_state["customer_research"]

    # Compile research findings with structured data
    all_findings = []
    structured_summaries = {}
    for phase_name, phase_data in research_data["research_phases"].items():
        for finding in phase_data["findings"]:
            if "structured_data" in finding:
                # Include structured data summary
                all_findings.append(
                    {
                        "phase": phase_name,
                        "structured_data": finding["structured_data"],
                        "research_topic": finding.get("research_topic", "N/A"),
                        "confidence_score": finding.get("confidence_score", 0.0),
                        "timestamp": finding["timestamp"],
                    }
                )
                structured_summaries[phase_name] = finding["structured_data"]
            else:
                # Fallback for non-structured data
                all_findings.append(
                    {
                        "phase": phase_name,
                        "content": str(finding.get("content", ""))[:500],
                        "timestamp": finding["timestamp"],
                    }
                )

    consolidation_prompt = f"""
    COMPREHENSIVE CUSTOMER RESEARCH CONSOLIDATION (STRUCTURED DATA):

    Original Query: {customer_query}
    Session ID: {research_data["workflow_id"]}
    Total Research Phases: {len(research_data["research_phases"])}
    Completed Steps: {research_data["research_metadata"]["completed_steps"]}

    STRUCTURED RESEARCH FINDINGS TO CONSOLIDATE:

    Customer Profile Research:
    {json.dumps(structured_summaries.get("profile", {}), indent=2) if "profile" in structured_summaries else "No structured data available"}

    Business Goals Research:
    {json.dumps(structured_summaries.get("business_goals", {}), indent=2) if "business_goals" in structured_summaries else "No structured data available"}

    Web Intelligence Research:
    {json.dumps(structured_summaries.get("web_intelligence", {}), indent=2) if "web_intelligence" in structured_summaries else "No structured data available"}

    CONSOLIDATION OBJECTIVES:
    1. Synthesize all structured research findings into cohesive customer insights
    2. Identify patterns, correlations, and key themes across customer profile, business goals, and web intelligence
    3. Create comprehensive consolidated view with strategic opportunities
    4. Highlight critical findings and cross-research correlations
    5. Provide executive summaries and high-level recommendations
    6. Structure response according to ConsolidatedResearch model

    Create a detailed, consolidated customer research report that integrates all structured findings.
    """

    try:
        consolidation_result_iterator = research_consolidation_team.arun(
            consolidation_prompt, stream=True, stream_events=True
        )

        async for event in consolidation_result_iterator:
            yield event

        # Get the actual response after streaming
        consolidation_result = research_consolidation_team.get_last_run_output()

        # Store consolidated insights in session state
        consolidated_insight = {
            "consolidation_timestamp": datetime.now().isoformat(),
            "structured_data": consolidation_result.content,
            "research_phases_included": list(research_data["research_phases"].keys()),
            "total_findings_consolidated": len(all_findings),
        }

        session_state["customer_research"]["consolidated_insights"].append(
            consolidated_insight
        )

        # Return the structured Pydantic data directly
        yield StepOutput(content=consolidation_result.content, success=True)

    except Exception as e:
        yield StepOutput(
            content=f"Research consolidation failed: {str(e)}", success=False
        )


async def task_recommender_step(
    step_input: StepInput, session_state: dict
) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
    """
    Generate actionable task recommendations based on consolidated research
    """
    customer_query = step_input.input

    research_data = session_state["customer_research"]
    workflow_config = session_state["workflow_config"]
    research_prefs = session_state["research_preferences"]

    # Get latest consolidated insights
    latest_insights = (
        research_data["consolidated_insights"][-1]
        if research_data["consolidated_insights"]
        else {}
    )
    consolidated_structured_data = (
        latest_insights.get("structured_data", {}) if latest_insights else {}
    )

    recommendation_prompt = f"""
    STRATEGIC TASK RECOMMENDATIONS REQUEST (BASED ON STRUCTURED DATA):

    Research Query: {customer_query}
    Session Context: {research_data["workflow_id"]}

    CONSOLIDATED RESEARCH INSIGHTS (STRUCTURED):
    {json.dumps(consolidated_structured_data, indent=2) if consolidated_structured_data else "No structured consolidated research available"}

    WORKFLOW CONFIGURATION:
    - Research Depth: {workflow_config["research_depth"]}
    - Focus Areas: {", ".join(workflow_config["focus_areas"])}
    - Recommendation Type: {research_prefs["recommendation_type"]}
    - Reporting Level: {research_prefs["reporting_level"]}

    SESSION RESEARCH SUMMARY:
    - Total Research Phases: {len(research_data["research_phases"])}
    - Completed Analysis Steps: {research_data["research_metadata"]["completed_steps"]}
    - Research Duration: Session-based analysis

    RECOMMENDATION OBJECTIVES:
    1. Generate specific, actionable tasks based on research findings
    2. Prioritize recommendations by impact, urgency, and feasibility
    3. Create detailed action plans with timelines and success metrics
    4. Align recommendations with identified customer goals and pain points
    5. Provide implementation guidance and resource requirements

    Create comprehensive task recommendations with clear action items and strategic priorities.
    """

    try:
        recommendation_result_iterator = task_recommender_agent.arun(
            recommendation_prompt, stream=True, stream_events=True
        )

        async for event in recommendation_result_iterator:
            yield event

        # Get the actual response after streaming
        recommendation_result = task_recommender_agent.get_last_run_output()

        # Store recommendations in session state
        recommendation_data = {
            "recommendation_timestamp": datetime.now().isoformat(),
            "structured_data": recommendation_result.content,
            "based_on_insights": len(research_data["consolidated_insights"]),
            "recommendation_type": research_prefs["recommendation_type"],
        }

        session_state["customer_research"]["recommendations"].append(
            recommendation_data
        )

        # Final session state update
        session_state["customer_research"]["research_metadata"]["completed_at"] = (
            datetime.now().isoformat()
        )
        session_state["customer_research"]["research_metadata"]["final_status"] = (
            "completed_successfully"
        )

        # Return the structured Pydantic data directly
        yield StepOutput(content=recommendation_result.content, success=True)

    except Exception as e:
        yield StepOutput(
            content=f"Task recommendation generation failed: {str(e)}", success=False
        )


# Define workflow steps
set_session_state_step_obj = Step(
    name="Set Session State",
    executor=set_session_state_step,
)

customer_profile_research_step_obj = Step(
    name="Customer Profile Research",
    executor=customer_profile_research_step,
)

customer_biz_goals_research_step_obj = Step(
    name="Customer Business Goals Research",
    executor=customer_biz_goals_research_step,
)

web_intelligence_research_step_obj = Step(
    name="Web Intelligence Research",
    executor=web_intelligence_research_step,
)

customer_report_consolidation_step_obj = Step(
    name="Customer Report Consolidation",
    executor=customer_report_consolidation_step,
)

task_recommender_step_obj = Step(
    name="Task Recommender",
    executor=task_recommender_step,
)

# Create the comprehensive customer research workflow
customer_research_workflow = Workflow(
    name="Customer Research Pipeline",
    description="Comprehensive customer research with parallel execution and session state management",
    db=SqliteDb(
        session_table="customer_research_sessions",
        db_file="tmp/customer_research_workflow.db",
    ),
    steps=[
        set_session_state_step_obj,
        Parallel(
            customer_profile_research_step_obj,
            customer_biz_goals_research_step_obj,
            web_intelligence_research_step_obj,
            name="Parallel Research Phase",
        ),
        customer_report_consolidation_step_obj,
        task_recommender_step_obj,
    ],
)

agent_os = AgentOS(
    description="Example OS setup",
    workflows=[customer_research_workflow],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="customer_research_workflow_parallel:app", reload=True)

# # Example usage
# async def main():
#     print("🔍 Starting Comprehensive Customer Research Workflow...")
#     print("=" * 70)

#     # Example customer research query
#     research_query = "Analyze SaaS startup customers in the healthcare technology space, focusing on mid-market companies (50-500 employees) looking for patient management solutions"

#     # Run the workflow
#     result = await customer_research_workflow.aprint_response(
#         input=research_query,
#         markdown=True,
#         stream=True,
#     )

#     print("\n" + "=" * 70)
#     print("✅ Customer Research Workflow Completed Successfully!")

# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(main())
