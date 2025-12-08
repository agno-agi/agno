from textwrap import dedent

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

compression_manager = CompressionManager(
    compress_context_token_limit=15000,
)

agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[
        DuckDuckGoTools(),
    ],
    # Research instructions
    instructions=[
        "1. Initial Research & Discovery:",
        "   - Use search tool to find information about the target company",
        "   - Search for '[company name] competitors', 'companies like [company name]'",
        "   - Search for industry reports and market analysis",
        "2. Competitor Identification:",
        "   - Search for each identified competitor using Firecrawl",
        "   - Find their official websites and key information sources",
        "   - Map out the competitive landscape",
        "3. Website Analysis:",
        "   - Scrape competitor websites using Firecrawl",
        "   - Map their site structure to understand their offerings",
        "   - Extract product information, pricing, and value propositions",
        "4. Deep Competitive Analysis:",
        "   - Use the analyze tool after gathering information on each competitor",
        "   - Compare features, pricing, and market positioning",
        "   - Identify patterns and competitive dynamics",
        "5. Strategic Synthesis:",
        "   - Conduct SWOT analysis for each major competitor",
        "   - Use reasoning to identify competitive advantages",
        "   - Develop strategic recommendations",
    ],
    expected_output=dedent("""\
    # Competitive Analysis Report: {Target Company}

    ## Executive Summary
    {High-level overview of competitive landscape and key findings}

    ## Competitor Analysis
    {Detailed analysis of each competitor}

    ## Comparative Analysis
    {Feature and pricing comparisons}

    ## Strategic Recommendations
    {Actionable insights and next steps}
    """),
    db=SqliteDb(db_file="tmp/dbs/competitor_compression.db"),
    compression_manager=compression_manager,
    compress_context=True,
    add_history_to_context=True,
    num_history_runs=10,
    session_id="competitor_compression_demo",
    markdown=True,
    add_datetime_to_context=True,
)

agent.print_response(
    dedent("""\
    Analyze the competitive landscape for Notion in the productivity/workspace market.
    
    Focus on:
    1. Identify top 3 direct competitors
    2. For each competitor, find:
       - Key product features
       - Pricing model
       - Target market
    3. Compare their market positioning
    
    Use search and crawl tools to gather real data.\
    """),
    stream=True,
)

agent.print_response(
    "Based on your research, which competitor has the best pricing for small teams?",
    stream=True,
)

agent.print_response(
    "What feature gaps does Notion have compared to the competitors you analyzed?",
    stream=True,
)

agent.print_response(
    "Summarize all the competitors you've analyzed and your key recommendations.",
    stream=True,
)
