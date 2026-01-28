from textwrap import dedent

from agno.agent import Agent
from agno.compression import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.parallel import ParallelTools

compression_manager = CompressionManager(
    compress_context=True,
)

competitor_analysis_agent = Agent(
    model=Gemini(id="gemini-2.5-pro"),
    tools=[
        DuckDuckGoTools(),
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
    session_id="competitor_analysis_compression1_gemini",
    # Database for session persistence
    db=SqliteDb(db_file="tmp/dbs/competitor_analysis_compression.db"),
    compression_manager=compression_manager,
    add_history_to_context=True,
    num_history_runs=10,
    markdown=True,
    add_datetime_to_context=True,
    debug_mode=True,
)

competitor_analysis_agent.print_response(
    dedent("""\
    Analyze the competitive landscape for Anthropic in the AI/LLM space.
    Identify their main competitors and their key differentiators."""),
    stream=True,
)

competitor_analysis_agent.print_response(
    dedent("""\
    Based on your analysis, do a deeper comparison of:
    - OpenAI vs Anthropic pricing and model offerings
    - Google DeepMind vs Anthropic research focus
    What are the key strategic differences?"""),
    stream=True,
)

competitor_analysis_agent.print_response(
    dedent("""\
    Given your competitive analysis, what strategic moves should
    Anthropic consider to strengthen their market position?
    Focus on product, pricing, and partnership opportunities."""),
    stream=True,
)
