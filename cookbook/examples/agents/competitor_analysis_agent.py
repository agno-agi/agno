"""🔍 Competitor Analysis Agent - Your AI-Powered Market Intelligence System!

This example demonstrates how to build a sophisticated competitor analysis agent that combines powerful search and scraping capabilities with advanced reasoning tools to provide
comprehensive competitive intelligence. The agent performs deep analysis of competitors including
market positioning, product offerings, and strategic insights.

Key capabilities:
- Company discovery using Firecrawl search
- Website scraping and content analysis
- Competitive intelligence gathering
- SWOT analysis with reasoning
- Strategic recommendations
- Structured thinking and analysis

Example queries to try:
- "Analyze OpenAI's main competitors in the LLM space"
- "Compare Uber vs Lyft in the ride-sharing market"
- "Analyze Tesla's competitive position vs traditional automakers"
- "Research fintech competitors to Stripe"
- "Analyze Nike vs Adidas in the athletic apparel market"

Dependencies: `pip install openai firecrawl-py agno`
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.firecrawl import FirecrawlTools
from agno.tools.reasoning import ReasoningTools

competitor_analysis_agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    tools=[
        FirecrawlTools(
            enable_search=True,
            enable_crawl=True,
            enable_mapping=True,
            formats=["markdown", "links", "html"],
            search_params={
                "limit": 2,
            },
            limit=5,
        ),
        ReasoningTools(
            add_instructions=True,
        ),
    ],
    instructions=[
        "1. Initial Research & Discovery:",
        "   - Use search tool to find information about the target company",
        "   - Search for '[company name] competitors', 'companies like [company name]'",
        "   - Search for industry reports and market analysis",
        "   - Use the think tool to plan your research approach",
        "2. Competitor Identification:",
        "   - Search for each identified competitor using Firecrawl",
        "   - Find their official websites and key information sources",
        "   - Map out the competitive landscape",
        "3. Website Analysis:",
        "   - Scrape competitor websites using Firecrawl",
        "   - Map their site structure to understand their offerings",
        "   - Extract product information, pricing, and value propositions",
        "   - Look for case studies and customer testimonials",
        "4. Deep Competitive Analysis:",
        "   - Use the analyze tool after gathering information on each competitor",
        "   - Compare features, pricing, and market positioning",
        "   - Identify patterns and competitive dynamics",
        "   - Think through the implications of your findings",
        "5. Strategic Synthesis:",
        "   - Conduct SWOT analysis for each major competitor",
        "   - Use reasoning to identify competitive advantages",
        "   - Analyze market trends and opportunities",
        "   - Develop strategic recommendations",
        "- Always use the think tool before starting major research phases",
        "- Use the analyze tool to process findings and draw insights",
        "- Search for multiple perspectives on each competitor",
        "- Verify information by checking multiple sources",
        "- Be thorough but focused in your analysis",
        "- Provide evidence-based recommendations",
    ],
    expected_output=dedent("""\
    # Competitive Analysis Report: {Target Company}

    ## Executive Summary
    {High-level overview of competitive landscape and key findings}

    ## Research Methodology
    - Search queries used
    - Websites analyzed
    - Key information sources

    ## Market Overview
    ### Industry Context
    - Market size and growth rate
    - Key trends and drivers
    - Regulatory environment

    ### Competitive Landscape
    - Major players identified
    - Market segmentation
    - Competitive dynamics

    ## Competitor Analysis

    ### Competitor 1: {Name}
    #### Company Overview
    - Website: {URL}
    - Founded: {Year}
    - Headquarters: {Location}
    - Company size: {Employees/Revenue if available}

    #### Products & Services
    - Core offerings
    - Key features and capabilities
    - Pricing model and tiers
    - Target market segments

    #### Digital Presence Analysis
    - Website structure and user experience
    - Key messaging and value propositions
    - Content strategy and resources
    - Customer proof points

    #### SWOT Analysis
    **Strengths:**
    - {Evidence-based strengths}

    **Weaknesses:**
    - {Identified weaknesses}

    **Opportunities:**
    - {Market opportunities}

    **Threats:**
    - {Competitive threats}

    ### Competitor 2: {Name}
    {Similar structure as above}

    ### Competitor 3: {Name}
    {Similar structure as above}

    ## Comparative Analysis

    ### Feature Comparison Matrix
    | Feature | {Target} | Competitor 1 | Competitor 2 | Competitor 3 |
    |---------|----------|--------------|--------------|--------------|
    | {Feature 1} | ✓/✗ | ✓/✗ | ✓/✗ | ✓/✗ |
    | {Feature 2} | ✓/✗ | ✓/✗ | ✓/✗ | ✓/✗ |

    ### Pricing Comparison
    | Company | Entry Level | Professional | Enterprise |
    |---------|-------------|--------------|------------|
    | {Pricing details extracted from websites} |

    ### Market Positioning Analysis
    {Analysis of how each competitor positions themselves}

    ## Strategic Insights

    ### Key Findings
    1. {Major insight with evidence}
    2. {Competitive dynamics observed}
    3. {Market gaps identified}

    ### Competitive Advantages
    - {Target company's advantages}
    - {Unique differentiators}

    ### Competitive Risks
    - {Main threats from competitors}
    - {Market challenges}

    ## Strategic Recommendations

    ### Immediate Actions (0-3 months)
    1. {Quick competitive responses}
    2. {Low-hanging fruit opportunities}

    ### Short-term Strategy (3-12 months)
    1. {Product/service enhancements}
    2. {Market positioning adjustments}

    ### Long-term Strategy (12+ months)
    1. {Sustainable differentiation}
    2. {Market expansion opportunities}

    ## Conclusion
    {Summary of competitive position and strategic imperatives}
    """),
    markdown=True,
    add_datetime_to_context=True,
    stream_events=True,
)

competitor_analysis_agent.print_response(
    """\
    Analyze the competitive landscape for Stripe in the payments industry.
    Focus on their products, pricing models, and market positioning.\
    """,
    stream=True,
    show_full_reasoning=True,
    debug_mode=True,
)
