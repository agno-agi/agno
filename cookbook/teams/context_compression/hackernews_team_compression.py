"""HackerNews Team with Context Compression

This example demonstrates how to use context compression with a multi-agent
team that researches HackerNews stories. The team uses multiple specialized
agents (researcher, web searcher, article reader) that share interactions,
which can quickly build up large context.

Key features:
- Compresses shared member interactions (share_member_interactions=True)
- Handles multiple agents with different tools
- Preserves key findings from HackerNews, web searches, and article content
- Enables continuous research across multiple queries

When to use this pattern:
- Teams with many specialized agents
- Teams that share interactions between members
- Research teams that accumulate data from multiple sources
- Any team where member responses create large context

Dependencies: `pip install openai ddgs newspaper4k lxml_html_clean agno`
"""

from typing import List

from agno.agent import Agent
from agno.compression import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.newspaper4k import Newspaper4kTools
from pydantic import BaseModel


class Article(BaseModel):
    """Structured output for the team's research."""

    title: str
    summary: str
    key_insights: List[str]
    reference_links: List[str]


# Specialized agent for HackerNews research
hn_researcher = Agent(
    name="HackerNews Researcher",
    model=OpenAIChat("gpt-4o-mini"),
    role="Gets top stories and discussions from HackerNews.",
    tools=[HackerNewsTools()],
    instructions=[
        "Find relevant stories on HackerNews",
        "Extract story titles, URLs, and discussion links",
        "Focus on the most upvoted and discussed items",
    ],
)

# Specialized agent for web searching
web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIChat("gpt-4o-mini"),
    role="Searches the web for additional context and information.",
    tools=[DuckDuckGoTools()],
    instructions=[
        "Search for additional context on topics",
        "Find recent news and updates",
        "Cross-reference information from multiple sources",
    ],
    add_datetime_to_context=True,
)

# Specialized agent for reading articles
article_reader = Agent(
    name="Article Reader",
    model=OpenAIChat("gpt-4o-mini"),
    role="Reads and summarizes articles from URLs.",
    tools=[Newspaper4kTools()],
    instructions=[
        "Extract key information from article content",
        "Summarize main points concisely",
        "Note important quotes and statistics",
    ],
)

# Create a compression manager for team context
# Lower threshold since member interactions add up quickly
compression_manager = CompressionManager(
    compress_context=True,
    compress_token_limit=12000,  # Compress when context exceeds this limit
)

# Create the team with compression enabled
hn_team = Team(
    name="HackerNews Research Team",
    model=OpenAIChat("gpt-4o"),
    members=[hn_researcher, web_searcher, article_reader],
    instructions=[
        "Coordinate research across team members:",
        "1. First, ask the HackerNews Researcher to find relevant stories",
        "2. Ask the Article Reader to read and summarize key articles",
        "3. Ask the Web Searcher to find additional context",
        "4. Synthesize findings into a comprehensive article",
        "Always provide the article reader with specific URLs to read.",
    ],
    output_schema=Article,
    # Enable sharing member interactions - this is what builds context
    share_member_interactions=True,
    # Database and compression for session management
    db=SqliteDb(db_file="tmp/dbs/hackernews_team_compression.db"),
    compression_manager=compression_manager,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
)

if __name__ == "__main__":
    # First research task - get top stories
    print("=" * 60)
    print("Research Task 1: Top HackerNews Stories")
    print("=" * 60)
    hn_team.print_response(
        "Research the top 3 stories on HackerNews right now. Read the articles and provide context.",
        stream=True,
    )

    # Second task - deeper analysis (may trigger compression)
    print("\n" + "=" * 60)
    print("Research Task 2: AI/ML Focus")
    print("=" * 60)
    hn_team.print_response(
        "Now find and analyze the top AI/ML related stories on HackerNews. How do they relate to what you found earlier?",
        stream=True,
    )

    # Third task - synthesis (uses compressed context)
    print("\n" + "=" * 60)
    print("Research Task 3: Trend Analysis")
    print("=" * 60)
    hn_team.print_response(
        "Based on all your research, what are the key technology trends being discussed on HackerNews today?",
        stream=True,
    )

    # Show compression statistics
    if compression_manager.stats:
        print("\n" + "=" * 60)
        print("Compression Statistics:")
        print("=" * 60)
        for key, value in compression_manager.stats.items():
            print(f"  {key}: {value}")
