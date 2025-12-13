"""Research Agent with Context Compression

This example demonstrates how to use context compression with a research agent
that performs multiple sequential research tasks. As the agent accumulates
search results and analysis across queries, the context can exceed token limits.
Context compression automatically summarizes completed work while preserving
key facts, sources, and findings.

Key features:
- CompressionManager with token-based triggering
- Preserves structured research data (facts, sources, dates)
- Works across multiple research queries in a session
- Maintains journalistic quality while managing context size

When to use this pattern:
- Research agents that perform multiple searches per query
- Multi-turn research sessions building on previous findings
- Agents that extract and cite information from many sources

Dependencies: `pip install openai ddgs newspaper4k lxml_html_clean agno`
"""

from textwrap import dedent

from agno.agent import Agent
from agno.compression import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.newspaper4k import Newspaper4kTools

# Create a compression manager with token-based triggering
# When context exceeds 15000 tokens, completed tool calls are summarized
compression_manager = CompressionManager(
    compress_context=True,
    compress_token_limit=15000,  # Compress when context exceeds this limit
)

# Initialize the research agent with compression enabled
research_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(), Newspaper4kTools()],
    description=dedent("""\
        You are an elite investigative journalist with decades of experience.
        Your expertise encompasses:

        - Deep investigative research and analysis
        - Meticulous fact-checking and source verification
        - Compelling narrative construction
        - Data-driven reporting
        - Trend analysis and future predictions
        - Balanced perspective presentation\
    """),
    instructions=dedent("""\
        1. Research Phase
           - Search for authoritative sources on the topic
           - Prioritize recent publications and expert opinions
           - Identify key stakeholders and perspectives

        2. Analysis Phase
           - Extract and verify critical information
           - Cross-reference facts across multiple sources
           - Identify emerging patterns and trends

        3. Writing Phase
           - Craft an attention-grabbing headline
           - Include relevant quotes and statistics
           - Maintain objectivity and balance

        4. Quality Control
           - Verify all facts and attributions
           - Include source citations
    """),
    expected_output=dedent("""\
        # {Compelling Headline}

        ## Executive Summary
        {Concise overview of key findings}

        ## Key Findings
        {Main discoveries with sources}
        {Statistical evidence}

        ## Future Outlook
        {Emerging trends and predictions}

        ## Sources
        {List of sources with URLs}
    """),
    # Database for session persistence
    db=SqliteDb(db_file="tmp/dbs/research_agent_compression.db"),
    # Compression manager handles context size
    compression_manager=compression_manager,
    # Enable history so compression works across runs
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
    add_datetime_to_context=True,
    debug_mode=True,
)

if __name__ == "__main__":
    # First research task - builds initial context
    print("=" * 60)
    print("Research Task 1: AI Regulation")
    print("=" * 60)
    research_agent.print_response(
        "Research the current state of AI regulation worldwide. Focus on the EU AI Act, US executive orders, and China's approach.",
        stream=True,
    )

    # Second research task - context may be compressed here
    print("\n" + "=" * 60)
    print("Research Task 2: Quantum Computing")
    print("=" * 60)
    research_agent.print_response(
        "Now research the latest breakthroughs in quantum computing. Which companies are leading and what practical applications are emerging?",
        stream=True,
    )

    # Third task - builds on compressed context
    print("\n" + "=" * 60)
    print("Research Task 3: Intersection Analysis")
    print("=" * 60)
    research_agent.print_response(
        "Based on your research, analyze how quantum computing might impact AI development and what regulatory challenges this creates.",
        stream=True,
    )

    # Show compression statistics
    if compression_manager.stats:
        print("\n" + "=" * 60)
        print("Compression Statistics:")
        print("=" * 60)
        for key, value in compression_manager.stats.items():
            print(f"  {key}: {value}")
