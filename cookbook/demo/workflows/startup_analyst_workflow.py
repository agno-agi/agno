"""
Startup Analyst Workflow - Complete company/startup due diligence pipeline.

This workflow performs comprehensive analysis like a VC or M&A analyst:
1. Quick Snapshot - Gather initial intelligence
2. Deep Analysis - Market, competitive, and financial research
3. Critical Review - Challenge findings and identify risks
4. Final Report - Synthesize into actionable recommendations

Example queries:
- "Analyze this startup: Anthropic"
- "Due diligence on: OpenAI"
- "Should we invest in or partner with: Stripe?"
- "Evaluate this company as an acquisition target: Notion"
"""

import sys
from pathlib import Path
from textwrap import dedent
from typing import Dict, List, Optional

# Ensure module can be run from any directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from agno.workflow import Step, Workflow
from agno.workflow.parallel import Parallel
from agno.workflow.step import StepInput, StepOutput
from db import demo_db

# ============================================================================
# Phase 1: Quick Snapshot Agents
# ============================================================================
company_profiler = Agent(
    name="Company Profiler",
    role="Build initial company profile",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[ParallelTools(enable_search=True, enable_extract=True)],
    description="You create comprehensive company profiles.",
    instructions=dedent("""\
        Build a quick but thorough company profile:

        1. **Company Overview**
           - What they do (one paragraph)
           - Founded when, by whom
           - Headquarters and key locations
           - Employee count (if available)

        2. **Product/Service**
           - Main offerings
           - Target customers
           - Pricing model (if known)

        3. **Leadership**
           - Key executives
           - Notable board members
           - Founder background

        4. **Funding & Financials** (if available)
           - Total funding raised
           - Key investors
           - Valuation (if known)
           - Revenue indicators

        Be specific with numbers and dates. Cite sources.
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

market_analyst = Agent(
    name="Market Analyst",
    role="Analyze market position and competitive landscape",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[ParallelTools(enable_search=True, enable_extract=True)],
    description="You analyze markets and competitive dynamics.",
    instructions=dedent("""\
        Analyze the company's market position:

        1. **Market Size & Growth**
           - TAM/SAM/SOM if available
           - Market growth rate
           - Key market drivers

        2. **Competitive Landscape**
           - Top 3-5 competitors
           - Market share estimates
           - Competitive advantages/disadvantages

        3. **Positioning**
           - How they differentiate
           - Target segment focus
           - Pricing relative to competitors

        4. **Market Trends**
           - Key tailwinds
           - Emerging threats
           - Technology shifts

        Use specific data and comparisons. Be objective.
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

news_tracker = Agent(
    name="News Tracker",
    role="Track recent news and developments",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[ParallelTools(enable_search=True, enable_extract=True)],
    description="You track and summarize recent company news.",
    instructions=dedent("""\
        Find and summarize recent news and developments:

        1. **Recent Announcements** (last 6 months)
           - Product launches
           - Partnerships
           - Funding rounds
           - Executive changes

        2. **Press Coverage**
           - Positive coverage and wins
           - Negative coverage and concerns
           - Industry analyst opinions

        3. **Sentiment Indicators**
           - Overall tone of coverage
           - Customer/user sentiment
           - Employee sentiment (if available)

        Focus on the last 6 months. Include dates and sources.
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Phase 2: Deep Analysis Agent
# ============================================================================
strategic_analyst = Agent(
    name="Strategic Analyst",
    role="Deep strategic analysis",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[
        ReasoningTools(add_instructions=True),
        ParallelTools(enable_search=True, enable_extract=True),
    ],
    description="You perform deep strategic analysis.",
    instructions=dedent("""\
        Perform comprehensive strategic analysis:

        1. **Business Model Analysis**
           - Revenue streams and unit economics
           - Customer acquisition strategy
           - Retention and expansion model
           - Scalability assessment

        2. **Competitive Moat**
           - Network effects
           - Switching costs
           - Brand/reputation
           - Technology/IP
           - Data advantages
           - Regulatory capture

        3. **Growth Trajectory**
           - Historical growth (if available)
           - Growth drivers
           - Expansion opportunities
           - International potential

        4. **Strategic Risks**
           - Competitive threats
           - Technology disruption
           - Regulatory risks
           - Execution risks

        5. **SWOT Summary**
           | Strengths | Weaknesses |
           | Opportunities | Threats |

        Use reasoning tools to think through complex dynamics.
        Be analytical, not promotional.
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Phase 3: Critical Review Agent (Devil's Advocate)
# ============================================================================
critical_reviewer = Agent(
    name="Critical Reviewer",
    role="Challenge findings and identify risks",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[
        ReasoningTools(add_instructions=True),
        ParallelTools(enable_search=True, enable_extract=True),
    ],
    description="You critically review analysis and find weaknesses.",
    instructions=dedent("""\
        Your job is to stress-test the analysis. For each major finding:

        1. **Challenge Assumptions**
           - What's being assumed without evidence?
           - What would break if assumptions are wrong?

        2. **Find Counter-Evidence**
           - What would contradict the positive findings?
           - Are there critics or skeptics? What do they say?

        3. **Identify Risks**
           - What could go catastrophically wrong?
           - What risks are being downplayed?
           - What's the bear case?

        4. **Red Flags**
           - Leadership concerns
           - Financial warning signs
           - Market timing issues
           - Execution challenges

        5. **Assessment**
           - Overall risk level: Low / Medium / High
           - Biggest vulnerability
           - What would change your mind

        Be intellectually honest. Don't just criticize - identify
        what would need to be true for the investment to work.
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Phase 4: Final Report Agent
# ============================================================================
report_synthesizer = Agent(
    name="Report Synthesizer",
    role="Create final due diligence report",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[ReasoningTools(add_instructions=True)],
    description="You synthesize analysis into executive reports.",
    instructions=dedent("""\
        Create a comprehensive due diligence report.

        REPORT STRUCTURE:

        ## Due Diligence Report: [Company Name]

        ### Executive Summary
        - **Verdict**: [STRONG BUY / BUY / HOLD / PASS / STRONG PASS]
        - **Confidence**: [High / Medium / Low]
        - 5 key takeaways in bullet points

        ### Company Overview
        (1 paragraph summary)

        ### Investment Thesis
        #### Bull Case
        - Why this could be a great investment
        - Key value drivers

        #### Bear Case
        - Why this could fail
        - Key risks

        ### Detailed Analysis

        #### Market Position
        (Summary of market analysis)

        #### Competitive Dynamics
        (Summary of competitive landscape)

        #### Strategic Assessment
        (Summary of strategic analysis)

        #### Risk Assessment
        (Summary of critical review)

        ### Key Metrics
        | Metric | Value | Assessment |
        |--------|-------|------------|
        | Market Size | ... | ... |
        | Growth Rate | ... | ... |
        | Funding | ... | ... |
        | Competition | ... | ... |

        ### Recommendation

        **Overall Verdict**: [verdict with rationale]

        **Key Conditions**: What would need to be true for this to work

        **Due Diligence Items**: What to investigate further

        **Timeline**: When to revisit this analysis

        ---

        Make the report actionable. Be clear about the recommendation
        and what drives it. Don't hedge excessively.
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)


# ============================================================================
# Workflow Step Functions
# ============================================================================
async def consolidate_snapshot(input: StepInput) -> StepOutput:
    """Consolidate Phase 1 snapshot results."""
    previous_outputs: Optional[Dict[str, StepOutput]] = input.previous_step_outputs

    snapshot_output: Optional[StepOutput] = (
        previous_outputs.get("Quick Snapshot") if previous_outputs else None
    )

    parallel_steps: Optional[List[StepOutput]] = (
        snapshot_output.steps if snapshot_output else None
    )

    content = "## Phase 1: Quick Snapshot Complete\n\n"
    content += "The following intelligence has been gathered:\n\n"

    if parallel_steps and len(parallel_steps) > 0:
        for step_output in parallel_steps:
            content += f"### {step_output.step_name}\n\n"
            content += f"{step_output.content}\n\n"
            content += "---\n\n"

        return StepOutput(content=content, success=True)

    return StepOutput(content="No snapshot data gathered", success=False)


async def consolidate_all(input: StepInput) -> StepOutput:
    """Consolidate all analysis for final report."""
    previous_outputs: Optional[Dict[str, StepOutput]] = input.previous_step_outputs

    if not previous_outputs:
        return StepOutput(content="No analysis to consolidate", success=False)

    content = "## Complete Analysis for Final Report\n\n"
    content += "Synthesize all findings below into a cohesive due diligence report.\n\n"

    for step_name, output in previous_outputs.items():
        if output.content:
            content += f"### From: {step_name}\n\n"
            content += f"{output.content}\n\n"
            content += "---\n\n"

    return StepOutput(content=content, success=True)


# ============================================================================
# Create Workflow Steps
# ============================================================================
# Phase 1: Quick Snapshot (Parallel)
profiler_step = Step(name="Company Profile", agent=company_profiler)
market_step = Step(name="Market Analysis", agent=market_analyst)
news_step = Step(name="Recent News", agent=news_tracker)

consolidate_snapshot_step = Step(
    name="Consolidate Snapshot",
    executor=consolidate_snapshot,
)

# Phase 2: Deep Analysis
strategic_step = Step(name="Strategic Analysis", agent=strategic_analyst)

# Phase 3: Critical Review
critical_step = Step(name="Critical Review", agent=critical_reviewer)

# Phase 4: Final Report
consolidate_all_step = Step(name="Consolidate All", executor=consolidate_all)
report_step = Step(name="Final Report", agent=report_synthesizer)

# ============================================================================
# Create the Workflow
# ============================================================================
startup_analyst_workflow = Workflow(
    name="Startup Analyst Workflow",
    description=dedent("""\
        A comprehensive due diligence workflow that analyzes companies like a VC:
        1. Quick Snapshot - Company profile, market position, recent news
        2. Strategic Analysis - Deep dive on business model and competitive moat
        3. Critical Review - Challenge findings and identify risks
        4. Final Report - Synthesize into actionable recommendations
        """),
    steps=[
        Parallel(
            profiler_step,
            market_step,
            news_step,
            name="Quick Snapshot",
        ),  # type: ignore
        consolidate_snapshot_step,
        strategic_step,
        critical_step,
        consolidate_all_step,
        report_step,
    ],
    db=demo_db,
)

# ============================================================================
# Demo Tests
# ============================================================================
if __name__ == "__main__":
    import asyncio

    print("=" * 60)
    print("Startup Analyst Workflow")
    print("   4-phase: Snapshot -> Deep Analysis -> Critical Review -> Report")
    print("=" * 60)

    async def run_demo():
        if len(sys.argv) > 1:
            # Run with command line argument
            message = " ".join(sys.argv[1:])
            response = await startup_analyst_workflow.arun(message)
            print(response.content)
        else:
            # Run demo test
            print("\n--- Demo: Anthropic Due Diligence ---")
            response = await startup_analyst_workflow.arun(
                "Quick due diligence on Anthropic - give me a brief verdict."
            )
            print(response.content)

    asyncio.run(run_demo())
