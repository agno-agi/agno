"""🚀 Product Launch Orchestrator - End-to-End Launch Automation Workflow

This workflow demonstrates advanced Agno workflow patterns for product launch automation:
- Parallel market research from multiple perspectives
- Sequential content creation across 5 launch assets
- Grouped steps for asset packaging and checklist generation
- Early stop mechanism for market viability assessment
- Session state management for launch context
- Structured I/O with comprehensive Pydantic models

Business Value: Reduce launch prep from weeks to hours, ensure completeness, faster time-to-market
"""

from textwrap import dedent
from typing import Dict, List, Literal, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.wikipedia import WikipediaTools
from agno.workflow import Parallel, Step, Steps, Workflow
from agno.workflow.types import StepInput, StepOutput
from pydantic import BaseModel, Field

# ============================================================================
# Database Setup
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, id="product_launch_workflow_db")

# ============================================================================
# Pydantic Models for Structured I/O
# ============================================================================


class ProductLaunchRequest(BaseModel):
    """Input schema for product launch requests"""

    product_name: str = Field(description="Name of the product being launched")
    product_category: str = Field(description="Product category or industry")
    target_market: str = Field(description="Target market segment")
    key_features: List[str] = Field(description="List of key product features")
    pricing_model: Literal["freemium", "subscription", "one-time", "enterprise"] = (
        Field(description="Pricing model")
    )
    launch_date: Optional[str] = Field(
        default=None, description="Target launch date (YYYY-MM-DD)"
    )
    company_size: Optional[Literal["startup", "smb", "enterprise"]] = Field(
        default="startup", description="Company size"
    )


class MarketResearch(BaseModel):
    """Market research analysis output"""

    market_size: str = Field(description="Estimated market size and growth")
    competitive_landscape: str = Field(
        description="Key competitors and their positioning"
    )
    market_trends: List[str] = Field(description="Current market trends")
    opportunities: List[str] = Field(description="Market opportunities identified")
    threats: List[str] = Field(description="Potential threats and challenges")
    viability_score: float = Field(
        ge=0.0, le=10.0, description="Market viability score (0-10)"
    )
    recommendation: Literal["proceed", "proceed_with_caution", "stop"] = Field(
        description="Launch recommendation"
    )


class LaunchAsset(BaseModel):
    """Individual launch asset with metadata"""

    asset_type: Literal[
        "product_description",
        "landing_page",
        "press_release",
        "pricing_page",
        "technical_docs",
    ]
    content: str = Field(description="The actual asset content")
    target_audience: str = Field(description="Primary audience for this asset")
    word_count: int = Field(description="Content word count")
    key_messages: List[str] = Field(description="Key messages conveyed")
    call_to_action: str = Field(description="Primary call-to-action")


class LaunchChecklist(BaseModel):
    """Comprehensive launch checklist with timeline"""

    pre_launch_tasks: List[Dict[str, str]] = Field(
        description="Tasks to complete before launch (task, owner, deadline)"
    )
    launch_day_tasks: List[Dict[str, str]] = Field(description="Tasks for launch day")
    post_launch_tasks: List[Dict[str, str]] = Field(description="Tasks after launch")
    critical_dependencies: List[str] = Field(
        description="Critical dependencies to track"
    )
    risk_mitigation_plan: Dict[str, str] = Field(
        description="Risks and mitigation strategies"
    )
    success_metrics: List[str] = Field(description="KPIs to track post-launch")


class ProductLaunchOutput(BaseModel):
    """Complete product launch package"""

    market_analysis: MarketResearch
    launch_assets: List[LaunchAsset]
    launch_checklist: LaunchChecklist
    estimated_timeline: str = Field(description="Estimated timeline to launch")
    budget_estimate: str = Field(description="Estimated budget requirements")
    recommended_channels: List[str] = Field(
        description="Recommended distribution channels"
    )


# ============================================================================
# Market Research Agents (Parallel Execution)
# ============================================================================

market_trends_agent = Agent(
    name="Market Trends Analyst",
    model=Claude(id="claude-sonnet-4-0"),
    role="Analyze market trends and industry dynamics",
    tools=[DuckDuckGoTools(), WikipediaTools()],
    instructions=dedent("""\
        You are a market trends analyst specializing in technology product launches.

        Your responsibilities:
        1. Research current market trends and dynamics
        2. Identify emerging technologies and methodologies
        3. Assess market maturity and growth potential
        4. Analyze industry adoption patterns

        Focus on:
        - Market size and growth projections
        - Technology adoption curves
        - Industry pain points and needs
        - Regulatory and compliance factors

        Provide insights on:
        - Is the market ready for this product?
        - What trends favor or hinder adoption?
        - What's the estimated market size?
        - Growth trajectory and timeline
        \
    """),
)

competitor_intelligence_agent = Agent(
    name="Competitive Intelligence Analyst",
    model=Claude(id="claude-sonnet-4-0"),
    role="Analyze competitive landscape and positioning",
    tools=[DuckDuckGoTools()],
    instructions=dedent("""\
        You are a competitive intelligence analyst tracking competitor products and strategies.

        Your responsibilities:
        1. Identify direct and indirect competitors
        2. Analyze competitor strengths and weaknesses
        3. Assess competitive positioning and differentiation
        4. Identify market gaps and opportunities

        Research:
        - Who are the main competitors?
        - What are their key features and pricing?
        - How are they positioned in the market?
        - What are their weaknesses we can exploit?

        Provide insights on:
        - Competitive advantages we can claim
        - Differentiation opportunities
        - Competitive threats to address
        - Pricing positioning recommendations
        \
    """),
)

target_audience_agent = Agent(
    name="Target Audience Researcher",
    model=Claude(id="claude-sonnet-4-0"),
    role="Research target audience and persona development",
    tools=[WikipediaTools(), DuckDuckGoTools()],
    instructions=dedent("""\
        You are a target audience researcher developing detailed buyer personas.

        Your responsibilities:
        1. Define target audience demographics and psychographics
        2. Understand their goals, challenges, and pain points
        3. Identify decision-making criteria and processes
        4. Map the buyer journey and touchpoints

        Focus on:
        - Who is the ideal customer?
        - What problems are they trying to solve?
        - What are their evaluation criteria?
        - Who influences the buying decision?

        Provide insights on:
        - Detailed buyer personas
        - Pain points we address
        - Value propositions that resonate
        - Messaging and positioning recommendations
        \
    """),
)

# ============================================================================
# Market Viability Assessment (Early Stop Decision)
# ============================================================================

market_viability_assessor = Agent(
    name="Market Viability Assessor",
    model=Claude(id="claude-sonnet-4-0"),
    role="Assess overall market viability and provide launch recommendation",
    instructions=dedent("""\
        You are a senior product strategist assessing market viability for product launches.

        Your responsibilities:
        1. Synthesize market research findings
        2. Evaluate market opportunity vs. risks
        3. Assess competitive positioning potential
        4. Provide clear launch recommendation

        Viability criteria:
        - Market size: Is it large enough? Growing?
        - Competition: Can we differentiate and compete?
        - Timing: Is the market ready for this?
        - Resources: Do we have what's needed?

        Scoring guidelines (0-10):
        - 8-10: Strong go - high potential, clear opportunity
        - 5-7: Proceed with caution - opportunities exist but risks present
        - 0-4: Stop - significant risks, unclear opportunity

        Provide:
        - Viability score (0-10)
        - Clear recommendation: proceed, proceed_with_caution, or stop
        - Key reasoning and critical factors
        - Risks and mitigation strategies
        \
    """),
    output_schema=MarketResearch,
)

# ============================================================================
# Content Creation Agents (Sequential Phases)
# ============================================================================

product_description_agent = Agent(
    name="Product Description Writer",
    model=Claude(id="claude-sonnet-4-0"),
    role="Create compelling product descriptions",
    instructions=dedent("""\
        You are an expert product copywriter creating compelling product descriptions.

        Your responsibilities:
        1. Craft clear, benefit-focused product descriptions
        2. Highlight key features and differentiators
        3. Address target audience pain points
        4. Create emotional connection with prospects

        Description structure:
        - Hook: Compelling opening statement
        - Problem: Pain point we solve
        - Solution: How our product helps
        - Features: Key capabilities and benefits
        - CTA: Clear call-to-action

        Writing style:
        - Clear and concise language
        - Benefit-driven (not just feature lists)
        - Customer-centric perspective
        - Persuasive but authentic tone
        \
    """),
    output_schema=LaunchAsset,
)

landing_page_agent = Agent(
    name="Landing Page Content Creator",
    model=Claude(id="claude-sonnet-4-0"),
    role="Create high-converting landing page copy",
    instructions=dedent("""\
        You are a conversion copywriter specializing in landing pages.

        Your responsibilities:
        1. Create attention-grabbing headlines
        2. Write persuasive body copy
        3. Develop compelling value propositions
        4. Craft effective calls-to-action

        Landing page sections:
        - Hero: Headline + subheadline + CTA
        - Problem: Pain points and challenges
        - Solution: How we solve them
        - Features: Key capabilities with benefits
        - Social Proof: Trust signals and validation
        - Pricing: Clear pricing information
        - Final CTA: Strong closing call-to-action

        Optimization for:
        - Conversion rates
        - SEO keywords
        - Mobile readability
        - Clear value proposition
        \
    """),
    output_schema=LaunchAsset,
)

press_release_agent = Agent(
    name="Press Release Writer",
    model=Claude(id="claude-sonnet-4-0"),
    role="Write professional press releases for media",
    instructions=dedent("""\
        You are a PR professional writing press releases for product launches.

        Your responsibilities:
        1. Follow standard press release format
        2. Create newsworthy narratives
        3. Include relevant quotes and data
        4. Provide clear contact information

        Press release structure:
        - Headline: Newsworthy and attention-grabbing
        - Dateline: City and date
        - Lead: Who, what, when, where, why
        - Body: Product details, benefits, quotes
        - Boilerplate: Company background
        - Contact: Media contact information

        Writing guidelines:
        - Third-person perspective
        - Newsworthy angle
        - Quotable sound bites
        - AP Style formatting
        \
    """),
    output_schema=LaunchAsset,
)

pricing_page_agent = Agent(
    name="Pricing Page Content Creator",
    model=Claude(id="claude-sonnet-4-0"),
    role="Create transparent, persuasive pricing content",
    instructions=dedent("""\
        You are a pricing strategist creating pricing page content.

        Your responsibilities:
        1. Present pricing clearly and transparently
        2. Highlight value at each pricing tier
        3. Address common pricing objections
        4. Guide customers to optimal plan

        Pricing page elements:
        - Plan comparison table
        - Feature breakdowns by tier
        - Value propositions per plan
        - Frequently asked questions
        - CTA for each pricing tier

        Best practices:
        - Clear, simple pricing
        - Highlight most popular plan
        - Show annual savings
        - Address "why this pricing"
        - Include testimonials/ROI data
        \
    """),
    output_schema=LaunchAsset,
)

technical_docs_agent = Agent(
    name="Technical Documentation Writer",
    model=Claude(id="claude-sonnet-4-0"),
    role="Create developer-focused technical documentation",
    instructions=dedent("""\
        You are a technical writer creating developer documentation.

        Your responsibilities:
        1. Write clear technical documentation
        2. Create getting started guides
        3. Document API endpoints and examples
        4. Provide troubleshooting guidance

        Documentation structure:
        - Overview: What the product does
        - Quick Start: 5-minute setup guide
        - Core Concepts: Key terminology and architecture
        - API Reference: Endpoints, parameters, responses
        - Code Examples: Real-world use cases
        - Troubleshooting: Common issues and solutions

        Writing style:
        - Clear, concise technical language
        - Step-by-step instructions
        - Code examples that work
        - Assume developer audience
        \
    """),
    output_schema=LaunchAsset,
)

# ============================================================================
# Launch Checklist Generator
# ============================================================================

launch_checklist_agent = Agent(
    name="Launch Checklist Generator",
    model=Claude(id="claude-sonnet-4-0"),
    role="Create comprehensive launch checklist and timeline",
    instructions=dedent("""\
        You are a product launch manager creating comprehensive launch checklists.

        Your responsibilities:
        1. Create detailed task lists for each launch phase
        2. Assign realistic timelines and owners
        3. Identify critical dependencies
        4. Develop risk mitigation plans
        5. Define success metrics

        Checklist phases:
        - Pre-launch (4-6 weeks out)
        - Launch week (1 week out)
        - Launch day
        - Post-launch (first 30 days)

        For each task include:
        - Task name and description
        - Responsible owner/team
        - Deadline (relative to launch date)
        - Dependencies
        - Success criteria

        Risk categories:
        - Technical risks
        - Market risks
        - Resource risks
        - Timeline risks

        Success metrics:
        - Acquisition metrics
        - Engagement metrics
        - Revenue metrics
        - Customer satisfaction
        \
    """),
    output_schema=LaunchChecklist,
)

# ============================================================================
# Custom Functions: Market Viability Check & Early Stop
# ============================================================================


def check_market_viability(step_input: StepInput) -> StepOutput:
    """
    Evaluate market viability and determine if launch should proceed.

    Early stop criteria:
    - Viability score < 5.0 → Stop launch
    - Recommendation = "stop" → Stop launch
    - Otherwise → Proceed to content creation

    Args:
        step_input: Contains market research data

    Returns:
        StepOutput with viability decision
    """
    # Get market research from previous step
    research_content = step_input.previous_step_content

    print("\n" + "=" * 80)
    print("🎯 MARKET VIABILITY ASSESSMENT")
    print("=" * 80)

    # Parse market research
    if isinstance(research_content, MarketResearch):
        viability_score = research_content.viability_score
        recommendation = research_content.recommendation

        print(f"\n📊 Market Analysis Results:")
        print(f"   Viability Score: {viability_score}/10")
        print(f"   Recommendation: {recommendation.upper()}")

        # Store in session state if available
        if (
            hasattr(step_input, "session_state")
            and step_input.session_state is not None
        ):
            step_input.session_state["viability_score"] = viability_score
            step_input.session_state["viability_recommendation"] = recommendation

        # Decision logic for early stop
        if viability_score < 5.0 or recommendation == "stop":
            print("\n   🛑 LAUNCH STOPPED - Market viability concerns")
            print(f"   Reason: {research_content.threats}")

            return StepOutput(
                content=f"""
🛑 **LAUNCH RECOMMENDATION: DO NOT PROCEED**

**Viability Score:** {viability_score}/10 (Below threshold of 5.0)

**Key Concerns:**
{chr(10).join(["- " + threat for threat in research_content.threats])}

**Recommendation:**
Consider pivoting the product or conducting additional market validation before proceeding with launch.
                """,
                stop=True,  # Stop workflow execution
            )

        elif recommendation == "proceed_with_caution":
            print("\n   ⚠️  PROCEED WITH CAUTION - Risks identified")

            return StepOutput(
                content=f"""
⚠️  **LAUNCH RECOMMENDATION: PROCEED WITH CAUTION**

**Viability Score:** {viability_score}/10

**Market Opportunities:**
{chr(10).join(["- " + opp for opp in research_content.opportunities])}

**Risks to Address:**
{chr(10).join(["- " + threat for threat in research_content.threats])}

Proceeding with content creation while monitoring risks...
                """,
                stop=False,  # Continue to content creation
            )

        else:  # proceed
            print("\n   ✅ LAUNCH APPROVED - Strong market opportunity")

            return StepOutput(
                content=f"""
✅ **LAUNCH RECOMMENDATION: PROCEED**

**Viability Score:** {viability_score}/10

**Market Opportunities:**
{chr(10).join(["- " + opp for opp in research_content.opportunities])}

**Competitive Advantages:**
- Clear market positioning identified
- Strong differentiation potential
- Favorable market timing

Proceeding with full launch preparation...
                """,
                stop=False,  # Continue to content creation
            )

    # Fallback: if can't parse, proceed with caution
    print("\n   ⚠️  Could not parse market research - proceeding with caution")
    return StepOutput(
        content="⚠️  Market analysis incomplete - proceeding with caution", stop=False
    )


# ============================================================================
# Workflow Steps Definition
# ============================================================================

# Step 1: Parallel market research
parallel_market_research = Parallel(
    Step(
        name="analyze_market_trends",
        agent=market_trends_agent,
        description="Analyze market trends and industry dynamics",
    ),
    Step(
        name="analyze_competitors",
        agent=competitor_intelligence_agent,
        description="Research competitive landscape and positioning",
    ),
    Step(
        name="research_target_audience",
        agent=target_audience_agent,
        description="Develop target audience personas and insights",
    ),
    name="Market Research Phase",
)

# Step 2: Market viability assessment
market_assessment_step = Step(
    name="assess_market_viability",
    agent=market_viability_assessor,
    description="Evaluate market viability and provide launch recommendation",
)

# Step 3: Viability check (early stop decision)
viability_check_step = Step(
    name="viability_check",
    executor=check_market_viability,
    description="Determine if launch should proceed based on viability",
)

# Step 4: Grouped content creation steps (sequential)
content_creation_sequence = Steps(
    name="Content Creation Phase",
    description="Create all launch assets in sequence",
    steps=[
        Step(
            name="create_product_description",
            agent=product_description_agent,
            description="Create compelling product description",
        ),
        Step(
            name="create_landing_page",
            agent=landing_page_agent,
            description="Create high-converting landing page copy",
        ),
        Step(
            name="create_press_release",
            agent=press_release_agent,
            description="Write professional press release",
        ),
        Step(
            name="create_pricing_page",
            agent=pricing_page_agent,
            description="Create pricing page content",
        ),
        Step(
            name="create_technical_docs",
            agent=technical_docs_agent,
            description="Create technical documentation",
        ),
    ],
)

# Step 5: Launch checklist generation
checklist_step = Step(
    name="generate_launch_checklist",
    agent=launch_checklist_agent,
    description="Create comprehensive launch checklist and timeline",
)

# ============================================================================
# Main Workflow Definition
# ============================================================================

product_launch_workflow = Workflow(
    name="Product Launch Orchestrator",
    description="End-to-end product launch automation with market validation and asset creation",
    db=db,
    steps=[
        # Phase 1: Market Research (Parallel)
        parallel_market_research,
        # Phase 2: Market Viability Assessment
        market_assessment_step,
        # Phase 3: Viability Check (Early Stop Decision Point)
        viability_check_step,
        # Phase 4: Content Creation (Grouped Sequential Steps)
        content_creation_sequence,
        # Phase 5: Launch Checklist Generation
        checklist_step,
    ],
    input_schema=ProductLaunchRequest,
    session_state={},  # Initialize empty session state for launch context
)


# ============================================================================
# Usage Example
# ============================================================================

if __name__ == "__main__":
    """
    Example usage demonstrating product launch workflow.
    """
    print("=" * 80)
    print("🚀 Product Launch Workflow - Demo Example")
    print("=" * 80)

    # Example: SaaS product launch
    launch_request = ProductLaunchRequest(
        product_name="AgentFlow AI",
        product_category="Developer Tools - AI Automation",
        target_market="B2B SaaS - Enterprise development teams",
        key_features=[
            "AI agent orchestration platform",
            "Visual workflow builder",
            "100+ pre-built integrations",
            "Enterprise-grade security",
            "Real-time monitoring and analytics",
        ],
        pricing_model="subscription",
        launch_date="2025-03-15",
        company_size="startup",
    )

    print("\n\n📝 Planning Product Launch...")
    print("-" * 80)
    print(f"Product: {launch_request.product_name}")
    print(f"Category: {launch_request.product_category}")
    print(f"Target Market: {launch_request.target_market}")
    print(f"Pricing Model: {launch_request.pricing_model}")
    print("-" * 80)

    product_launch_workflow.print_response(input=launch_request, stream=True)
