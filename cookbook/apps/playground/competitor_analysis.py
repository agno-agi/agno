"""🔍 Competitor Analysis Agent!

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
from agno.playground import Playground
from agno.storage.sqlite import SqliteStorage
from agno.tools.firecrawl import FirecrawlTools
from agno.tools.reasoning import ReasoningTools

competitor_analysis_agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    name="Competitor Analysis Agent",
    tools=[
        FirecrawlTools(
            search=True,
            scrape=True,
            mapping=True,
            formats=["markdown", "links", "html"],
            search_params={
                "limit": 2,
            },
            limit=5,
        ),
        ReasoningTools(add_instructions=True),
    ],
    description="You run competitor analysis for a company.",
    instructions=dedent("""\
        1. Initial Research & Discovery:
           - Use search tool to find information about the target company
           - Search for 'companies like [company name]'. Do only 1 search.
           - Search for industry reports and market analysis. Do only 1 search.
           - Use the think tool to plan your research approach.
        2. Competitor Identification:
           - Search for 3 identified competitor using Firecrawl.
           - Scrape competitor websites using Firecrawl.
           - Extract product information, pricing, and value propositions.
        3. Map out the competitive landscape.
           - Use the analyze tool after gathering information on each competitor
           - Compare features, pricing, and market positioning
           - Identify patterns and competitive dynamics
        4. Conduct SWOT analysis for each major competitor
           - Use reasoning to identify competitive advantages
           - Analyze market trends and opportunities
           - Develop strategic recommendations

        - Always use the think tool before starting major research phases
        - Use the analyze tool to process findings and draw insights
        - Be thorough but focused in your analysis
        - Provide evidence-based recommendations
    """),
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
    add_datetime_to_instructions=True,
    storage=SqliteStorage(
        table_name="competitor_analysis",
        db_file="tmp/competitor_analysis.db",
    ),
)


playground = Playground(
    agents=[competitor_analysis_agent],
    name="Competitor Analysis",
    description="Agents for competitor analysis",
    app_id="competitor-analysis",
)
app = playground.get_app(use_async=False)

if __name__ == "__main__":
    playground.serve(app="competitor_analysis:app", reload=True)
