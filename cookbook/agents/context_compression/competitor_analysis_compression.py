from textwrap import dedent

from agno.agent import Agent
from agno.compression import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.parallel import ParallelTools

compression_manager = CompressionManager(
    compress_context=True,
)

competitor_analysis_agent = Agent(
    model="google:gemini-2.5-pro",
    tools=[
        DuckDuckGoTools(verify_ssl=False),
        ParallelTools(),
    ],
    instructions=[
        "1. Initial Research & Discovery:",
        "   - Search for information about the target company",
        "   - Search for '[company name] competitors'",
        "   - Use the think tool to plan your research approach",
        "2. Competitor Identification:",
        "   - Search for each identified competitor",
        "   - Find their official websites and key information",
        "   - Map out the competitive landscape",
        "3. Deep Competitive Analysis:",
        "   - Use the analyze tool after gathering information",
        "   - Compare features, pricing, and market positioning",
        "   - Identify patterns and competitive dynamics",
        "4. Strategic Synthesis:",
        "   - Conduct SWOT analysis for each major competitor",
        "   - Develop strategic recommendations",
        "- Use the think tool before starting major research phases",
        "- Be thorough but focused in your analysis",
    ],
    expected_output=dedent("""\
    # Competitive Analysis Report: {Target Company}

    ## Executive Summary
    {High-level overview of competitive landscape}

    ## Competitive Landscape
    - Major players identified
    - Market positioning

    ## Competitor Analysis

    ### Competitor 1: {Name}
    - Overview and key offerings
    - Strengths and weaknesses
    - Market position

    ### Competitor 2: {Name}
    - Overview and key offerings
    - Strengths and weaknesses
    - Market position

    ## Feature Comparison
    | Feature | Target | Competitor 1 | Competitor 2 |
    |---------|--------|--------------|--------------|

    ## Strategic Recommendations
    - Immediate actions
    - Long-term strategy

    ## Sources
    {List of sources analyzed}
    """),
    session_id="competitor_analysis_compression1_gemini1",
    # Database for session persistence
    db=SqliteDb(db_file="tmp/dbs/competitor_analysis_compression2_gemini.db"),
    # Compression manager handles large web content
    compression_manager=compression_manager,
    # Enable history for multi-phase analysis
    add_history_to_context=True,
    num_history_runs=10,
    markdown=True,
    add_datetime_to_context=True,
    debug_mode=True,
)

if __name__ == "__main__":
    # Phase 1: Initial competitive landscape
    print("=" * 60)
    print("Phase 1: Initial Competitive Analysis")
    print("=" * 60)
    competitor_analysis_agent.print_response(
        dedent("""\
        Analyze the competitive landscape for Anthropic in the AI/LLM space.
        Identify their main competitors and their key differentiators."""),
        stream=True,
    )

    # Phase 2: Deep dive on specific competitors
    print("\n" + "=" * 60)
    print("Phase 2: Deep Dive on Key Competitors")
    print("=" * 60)
    competitor_analysis_agent.print_response(
        dedent("""\
        Based on your analysis, do a deeper comparison of:
        - OpenAI vs Anthropic pricing and model offerings
        - Google DeepMind vs Anthropic research focus
        What are the key strategic differences?"""),
        stream=True,
    )

    # Phase 3: Strategic recommendations
    print("\n" + "=" * 60)
    print("Phase 3: Strategic Recommendations")
    print("=" * 60)
    competitor_analysis_agent.print_response(
        dedent("""\
        Given your competitive analysis, what strategic moves should
        Anthropic consider to strengthen their market position?
        Focus on product, pricing, and partnership opportunities."""),
        stream=True,
    )

    # Phase 4: Multi-media input (should be preserved after compression)
    print("\n" + "=" * 60)
    print("Phase 4: Analysis with Multi-Media Input")
    print("=" * 60)
    competitor_analysis_agent.print_response(
        [
            {
                "type": "text",
                "text": dedent("""\
                    Here is new market data that just came in. Incorporate this into your analysis:

                    MARKET UPDATE Q4 2024:
                    - Anthropic Claude 3.5 Sonnet pricing: $3/$15 per 1M tokens (input/output)
                    - OpenAI GPT-4o pricing: $2.50/$10 per 1M tokens (input/output)
                    - Google Gemini 1.5 Pro: $1.25/$5 per 1M tokens (input/output)

                    NEW ANNOUNCEMENTS:
                    - Anthropic: Computer use capability launched
                    - OpenAI: Advanced Voice Mode with vision
                    - Google: Gemini 2.0 with native tool use"""),
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/Google_2015_logo.svg/1200px-Google_2015_logo.svg.png",
                },
            },
            {
                "type": "text",
                "text": "The image above shows Google's branding. How do these updates and Google's strong brand presence change your strategic recommendations for Anthropic?",
            },
        ],
        stream=True,
    )
