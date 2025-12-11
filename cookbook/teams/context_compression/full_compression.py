"""
Research Team with Context Management (Sync).

This example demonstrates a research team that uses DuckDuckGo to search the web and accumulate tool calls. The older messages and
tool call results are automatically compressed to keep the context below the token limit.

Run: python cookbook/teams/context_compression/full_compression.py
"""

from textwrap import dedent

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

compression_prompt = """
    You are a compression expert. Your goal is to compress web search results for a research team.
    
    YOUR GOAL: Extract only actionable competitive insights while being extremely concise.
    
    MUST PRESERVE:
    - Competitor names and specific actions (product launches, partnerships, acquisitions, pricing changes)
    - Exact numbers (revenue, market share, growth rates, pricing, headcount)
    - Precise dates (announcement dates, launch dates, deal dates)
    - Direct quotes from executives or official statements
    - Funding rounds and valuations
    
    MUST REMOVE:
    - Company history and background information
    - General industry trends (unless competitor-specific)
    - Analyst opinions and speculation (keep only facts)
    - Detailed product descriptions (keep only key differentiators and pricing)
    - Marketing fluff and promotional language
    
    OUTPUT FORMAT:
    Return a bullet-point list where each line follows this format:
    "[Company Name] - [Date]: [Action/Event] ([Key Numbers/Details])"
    
    Keep it under 200 words total. Be ruthlessly concise. Facts only.
    
    Example:
    - Acme Corp - Mar 15, 2024: Launched AcmeGPT at $99/user/month, targeting enterprise market
    - TechCo - Feb 10, 2024: Acquired DataStart for $150M, gaining 500 enterprise customers
"""

compression_manager = CompressionManager(
    model=OpenAIChat(id="gpt-4.1"),
    compress_context=True,
    compress_token_limit=10000,  # or compress_context_messages_limit
    compress_context_instructions=compression_prompt,
)

# Create specialized research agents
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

research_team = Team(
    name="Research Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[tech_researcher, business_analyst],
    tools=[DuckDuckGoTools()],  # Team uses DuckDuckGo for research
    description="Research team that investigates topics and provides analysis.",
    instructions=dedent("""
        You are a research coordinator that investigates topics comprehensively.
        
        Your Process:
        1. Use DuckDuckGo to search for a lot of information on the topic.
        2. Delegate detailed analysis to the appropriate specialist
        3. Synthesize research findings with specialist insights
        
        Guidelines:
        - Always start with web research using your DuckDuckGo tools. Try to get as much information as possible.
        - Choose the right specialist based on the topic (tech vs business)
        - Combine your research with specialist analysis
        - Provide comprehensive, well-sourced responses
    """).strip(),
    db=SqliteDb(db_file="tmp/dbs/full_compression_team.db"),
    show_members_responses=True,
    compression_manager=compression_manager,
    add_history_to_context=True,
    num_history_runs=5,
    session_id="full_compression_team_demo",
    markdown=True,
    add_datetime_to_context=True,
    debug_mode=True,
)

if __name__ == "__main__":
    research_team.print_response(
        "What are the latest developments in AI agents? Which companies dominate the market?",
        stream=True,
    )

    research_team.print_response(
        "Based on your research, which competitor has the best pricing for small teams?",
        stream=True,
    )

    research_team.print_response(
        "Summarize the key findings from your research.",
        stream=True,
    )
