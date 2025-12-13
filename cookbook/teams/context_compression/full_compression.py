"""
Full context compression for teams.

This example demonstrates how to use `compress_context` with teams to maintain
long-running research sessions while staying within token limits.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.compression import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

# Create specialized agents
tech_researcher = Agent(
    name="Alex",
    role="Technology Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=dedent("""
        You specialize in technology and AI research.
        - Focus on latest developments, trends, and breakthroughs
        - Provide concise, data-driven insights
        - Cite your sources
    """).strip(),
)

business_analyst = Agent(
    name="Sarah",
    role="Business Analyst",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=dedent("""
        You specialize in business and market analysis.
        - Focus on companies, markets, and economic trends
        - Provide actionable business insights
        - Include relevant data and statistics
    """).strip(),
)

# Create a compression manager with a token limit
compression_manager = CompressionManager(
    compress_context=True,
    compress_token_limit=8000,  # Compress when context exceeds 8000 tokens
)

research_team = Team(
    name="Research Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[tech_researcher, business_analyst],
    tools=[DuckDuckGoTools()],
    description="Research team that investigates topics and provides analysis.",
    instructions=dedent("""
        You are a research coordinator that investigates topics comprehensively.
        
        Your Process:
        1. Use DuckDuckGo to search for information on the topic
        2. Delegate detailed analysis to the appropriate specialist
        3. Synthesize research findings with specialist insights
        
        Guidelines:
        - Always start with web research
        - Choose the right specialist based on the topic
        - Provide comprehensive, well-sourced responses
    """).strip(),
    db=SqliteDb(db_file="tmp/research_team_full_compression.db"),
    compression_manager=compression_manager,
    add_history_to_context=True,
    num_history_runs=5,
    show_members_responses=True,
)

if __name__ == "__main__":
    # First research task
    research_team.print_response(
        "What are the latest developments in AI agents? Research OpenAI, Anthropic, and Google.",
        stream=True,
    )

    print("\n" + "=" * 50 + "\n")

    # Second task - builds on previous context
    research_team.print_response(
        "Compare the pricing and enterprise offerings of these companies.",
        stream=True,
    )

    print("\n" + "=" * 50 + "\n")

    # Third task - may trigger compression
    research_team.print_response(
        "Based on your research, which company would you recommend for a startup?",
        stream=True,
    )

    # Show compression stats
    if compression_manager.stats:
        print("\nCompression Statistics:")
        for key, value in compression_manager.stats.items():
            print(f"  {key}: {value}")
