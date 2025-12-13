"""Competitor Analysis Agent with Context Compression

This example demonstrates how to use context compression with a competitor
analysis agent that scrapes websites and performs deep competitive intelligence.
FirecrawlTools returns large amounts of HTML/markdown content, and multi-company
analysis can quickly exceed token limits.

Key features:
- Handles large web scraping results from FirecrawlTools
- Preserves key competitive data (pricing, features, positioning)
- Works with ReasoningTools for extended thinking
- Compresses completed analyses while keeping actionable insights

When to use this pattern:
- Competitive intelligence agents that scrape multiple websites
- Market research agents gathering data from many sources
- Any agent that processes large amounts of web content

Dependencies: `pip install openai firecrawl-py agno`
"""

from textwrap import dedent

from agno.agent import Agent
from agno.compression import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.reasoning import ReasoningTools

# Create a compression manager for web content
# Higher threshold since web scraping returns large content
compression_manager = CompressionManager(
    compress_context=True,
    compress_token_limit=20000,  # Higher limit for web content
)

competitor_analysis_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(),  # Using DuckDuckGo as Firecrawl requires API key
        ReasoningTools(add_instructions=True),
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
    # Database for session persistence
    db=SqliteDb(db_file="tmp/dbs/competitor_analysis_compression.db"),
    # Compression manager handles large web content
    compression_manager=compression_manager,
    # Enable history for multi-phase analysis
    add_history_to_context=True,
    num_history_runs=3,
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
        show_full_reasoning=True,
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
        show_full_reasoning=True,
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
        show_full_reasoning=True,
    )

    # Show compression statistics
    if compression_manager.stats:
        print("\n" + "=" * 60)
        print("Compression Statistics:")
        print("=" * 60)
        for key, value in compression_manager.stats.items():
            print(f"  {key}: {value}")
