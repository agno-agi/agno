"""
🚀 Startup Idea Validator - Your Personal Business Validation Assistant!

This workflow helps entrepreneurs validate their startup ideas by:
1. Clarifying and refining the core business concept
2. Evaluating originality compared to existing solutions
3. Defining clear mission and objectives
4. Conducting comprehensive market research and analysis

Why is this helpful?
--------------------------------------------------------------------------------
• Get objective feedback on your startup idea before investing resources
• Understand your total addressable market and target segments
• Validate assumptions about market opportunity and competition
• Define clear mission and objectives to guide execution

Who should use this?
--------------------------------------------------------------------------------
• Entrepreneurs and Startup Founders
• Product Managers and Business Strategists
• Innovation Teams
• Angel Investors and VCs doing initial screening

Example use cases:
--------------------------------------------------------------------------------
• New product/service validation
• Market opportunity assessment
• Competitive analysis
• Business model validation
• Target customer segmentation
• Mission/vision refinement

Quick Start:
--------------------------------------------------------------------------------
1. Install dependencies:
   pip install openai agno

2. Set environment variables:
   - OPENAI_API_KEY

3. Run:
   python startup_idea_validator.py

The workflow will guide you through validating your startup idea with AI-powered
analysis and research. Use the insights to refine your concept and business plan!
"""

import asyncio
from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.pprint import pprint_run_response
from agno.workflow.types import WorkflowExecutionInput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field


# --- Response models ---
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


class CompetitorAnalysis(BaseModel):
    competitors: str = Field(..., description="List of identified competitors.")
    swot_analysis: str = Field(..., description="SWOT analysis for each competitor.")
    positioning: str = Field(
        ..., description="Startup's potential positioning relative to competitors."
    )


class ValidationReport(BaseModel):
    executive_summary: str = Field(
        ..., description="Executive summary of the validation."
    )
    idea_assessment: str = Field(..., description="Assessment of the startup idea.")
    market_opportunity: str = Field(..., description="Market opportunity analysis.")
    competitive_landscape: str = Field(
        ..., description="Competitive landscape overview."
    )
    recommendations: str = Field(..., description="Strategic recommendations.")
    next_steps: str = Field(..., description="Recommended next steps.")


# --- Agents ---
idea_clarifier_agent = Agent(
    name="Idea Clarifier",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "Given a user's startup idea, your goal is to refine that idea.",
        "Evaluate the originality of the idea by comparing it with existing concepts.",
        "Define the mission and objectives of the startup.",
        "Provide clear, actionable insights about the core business concept.",
    ],
    add_history_to_context=True,
    add_datetime_to_context=True,
    output_schema=IdeaClarification,
    debug_mode=False,
)

market_research_agent = Agent(
    name="Market Research Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "You are provided with a startup idea and the company's mission and objectives.",
        "Estimate the total addressable market (TAM), serviceable available market (SAM), and serviceable obtainable market (SOM).",
        "Define target customer segments and their characteristics.",
        "Search the web for resources and data to support your analysis.",
        "Provide specific market size estimates with supporting data sources.",
    ],
    add_history_to_context=True,
    add_datetime_to_context=True,
    output_schema=MarketResearch,
)

competitor_analysis_agent = Agent(
    name="Competitor Analysis Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions=[
        "You are provided with a startup idea and market research data.",
        "Identify existing competitors in the market.",
        "Perform Strengths, Weaknesses, Opportunities, and Threats (SWOT) analysis for each competitor.",
        "Assess the startup's potential positioning relative to competitors.",
        "Search for recent competitor information and market positioning.",
    ],
    add_history_to_context=True,
    add_datetime_to_context=True,
    output_schema=CompetitorAnalysis,
    debug_mode=False,
)

report_agent = Agent(
    name="Report Generator",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are provided with comprehensive data about a startup idea including clarification, market research, and competitor analysis.",
        "Synthesize all information into a comprehensive validation report.",
        "Provide clear executive summary, assessment, and actionable recommendations.",
        "Structure the report professionally with clear sections and insights.",
        "Include specific next steps for the entrepreneur.",
    ],
    add_history_to_context=True,
    add_datetime_to_context=True,
    output_schema=ValidationReport,
    debug_mode=False,
)


# --- Execution function ---
async def startup_validation_execution(
    workflow: Workflow,
    execution_input: WorkflowExecutionInput,
    startup_idea: str,
    **kwargs: Any,
) -> str:
    """Execute the complete startup idea validation workflow"""

    # Get inputs
    message: str = execution_input.input
    idea: str = startup_idea

    if not idea:
        return "❌ No startup idea provided"

    print(f"🚀 Starting startup idea validation for: {idea}")
    print(f"💡 Validation request: {message}")

    # Phase 1: Idea Clarification
    print("\n🎯 PHASE 1: IDEA CLARIFICATION & REFINEMENT")
    print("=" * 60)

    clarification_prompt = f"""
    {message}

    Please analyze and refine the following startup idea:

    STARTUP IDEA: {idea}

    Evaluate:
    1. The originality of this idea compared to existing solutions
    2. Define a clear mission statement for this startup
    3. Outline specific, measurable objectives
    Provide insights on how to strengthen and focus the core concept.
    """

    print("🔍 Analyzing and refining the startup concept...")

    try:
        clarification_result = await idea_clarifier_agent.arun(clarification_prompt)
        idea_clarification = clarification_result.content

        print("✅ Idea clarification completed")
        print(f"📝 Mission: {idea_clarification.mission[:100]}...")

    except Exception as e:
        return f"❌ Failed to clarify idea: {str(e)}"

    # Phase 2: Market Research
    print("\n📊 PHASE 2: MARKET RESEARCH & ANALYSIS")
    print("=" * 60)

    market_research_prompt = f"""
    Based on the refined startup idea and clarification below, conduct comprehensive market research:
    STARTUP IDEA: {idea}
    ORIGINALITY: {idea_clarification.originality}
    MISSION: {idea_clarification.mission}
    OBJECTIVES: {idea_clarification.objectives}
    Please research and provide:
    1. Total Addressable Market (TAM) - overall market size
    2. Serviceable Available Market (SAM) - portion you could serve
    3. Serviceable Obtainable Market (SOM) - realistic market share
    4. Target customer segments with detailed characteristics
    Use web search to find current market data and trends.
    """

    print("📈 Researching market size and customer segments...")

    try:
        market_result = await market_research_agent.arun(market_research_prompt)
        market_research = market_result.content

        print("✅ Market research completed")
        print(f"🎯 TAM: {market_research.total_addressable_market[:100]}...")

    except Exception as e:
        return f"❌ Failed to complete market research: {str(e)}"

    # Phase 3: Competitor Analysis
    print("\n🏢 PHASE 3: COMPETITIVE LANDSCAPE ANALYSIS")
    print("=" * 60)

    competitor_prompt = f"""
    Based on the startup idea and market research below, analyze the competitive landscape:
    STARTUP IDEA: {idea}
    TAM: {market_research.total_addressable_market}
    SAM: {market_research.serviceable_available_market}
    SOM: {market_research.serviceable_obtainable_market}
    TARGET SEGMENTS: {market_research.target_customer_segments}
    Please research and provide:
    1. Identify direct and indirect competitors
    2. SWOT analysis for each major competitor
    3. Assessment of startup's potential competitive positioning
    4. Market gaps and opportunities
    Use web search to find current competitor information.
    """

    print("🔎 Analyzing competitive landscape...")

    try:
        competitor_result = await competitor_analysis_agent.arun(competitor_prompt)
        competitor_analysis = competitor_result.content

        print("✅ Competitor analysis completed")
        print(f"🏆 Positioning: {competitor_analysis.positioning[:100]}...")

    except Exception as e:
        return f"❌ Failed to complete competitor analysis: {str(e)}"

    # Phase 4: Final Validation Report
    print("\n📋 PHASE 4: COMPREHENSIVE VALIDATION REPORT")
    print("=" * 60)

    report_prompt = f"""
    Synthesize all the research and analysis into a comprehensive startup validation report:

    STARTUP IDEA: {idea}

    IDEA CLARIFICATION:
    - Originality: {idea_clarification.originality}
    - Mission: {idea_clarification.mission}
    - Objectives: {idea_clarification.objectives}
    MARKET RESEARCH:
    - TAM: {market_research.total_addressable_market}
    - SAM: {market_research.serviceable_available_market}
    - SOM: {market_research.serviceable_obtainable_market}
    - Target Segments: {market_research.target_customer_segments}
    COMPETITOR ANALYSIS:
    - Competitors: {competitor_analysis.competitors}
    - SWOT: {competitor_analysis.swot_analysis}
    - Positioning: {competitor_analysis.positioning}
    Create a professional validation report with:
    1. Executive summary
    2. Idea assessment (strengths/weaknesses)
    3. Market opportunity analysis
    4. Competitive landscape overview
    5. Strategic recommendations
    6. Specific next steps for the entrepreneur
    """

    print("📝 Generating comprehensive validation report...")

    try:
        final_result = await report_agent.arun(report_prompt)
        validation_report = final_result.content

        print("✅ Validation report completed")

    except Exception as e:
        return f"❌ Failed to generate final report: {str(e)}"

    # Final summary
    summary = f"""
    🎉 STARTUP IDEA VALIDATION COMPLETED!
    📊 Validation Summary:
    • Startup Idea: {idea}
    • Idea Clarification: ✅ Completed
    • Market Research: ✅ Completed
    • Competitor Analysis: ✅ Completed
    • Final Report: ✅ Generated

    📈 Key Market Insights:
    • TAM: {market_research.total_addressable_market[:150]}...
    • Target Segments: {market_research.target_customer_segments[:150]}...

    🏆 Competitive Positioning:
    {competitor_analysis.positioning[:200]}...

    📋 COMPREHENSIVE VALIDATION REPORT:

    ## Executive Summary
    {validation_report.executive_summary}

    ## Idea Assessment
    {validation_report.idea_assessment}

    ## Market Opportunity
    {validation_report.market_opportunity}

    ## Competitive Landscape
    {validation_report.competitive_landscape}

    ## Strategic Recommendations
    {validation_report.recommendations}

    ## Next Steps
    {validation_report.next_steps}

    ⚠️ Disclaimer: This validation is for informational purposes only. Conduct additional due diligence before making investment decisions.
    """

    return summary


# --- Workflow definition ---
startup_validation_workflow = Workflow(
    name="Startup Idea Validator",
    description="Comprehensive startup idea validation with market research and competitive analysis",
    db=SqliteDb(
        session_table="workflow_session",
        db_file="tmp/workflows.db",
    ),
    steps=startup_validation_execution,
    session_state={},  # Initialize empty workflow session state
)


if __name__ == "__main__":

    async def main():
        from rich.prompt import Prompt

        # Get idea from user
        idea = Prompt.ask(
            "[bold]What is your startup idea?[/bold]\n✨",
            default="A marketplace for Christmas Ornaments made from leather",
        )

        print("🧪 Testing Startup Idea Validator with New Workflow Structure")
        print("=" * 70)

        result = await startup_validation_workflow.arun(
            input="Please validate this startup idea with comprehensive market research and competitive analysis",
            startup_idea=idea,
        )

        pprint_run_response(result, markdown=True)

    asyncio.run(main())
