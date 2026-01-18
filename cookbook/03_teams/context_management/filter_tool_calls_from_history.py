"""
Research Team with Context Management.

This example demonstrates a research team that uses DuckDuckGo to search the web and accumulate tool calls. The older research results
are automatically filtered out to keep the context focused on recent research results.

When max_tool_calls_from_history is set to 3, the team will keep only the last 3 tool call results.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

# Create specialized research agents
tech_researcher = Agent(
    name="Alex",
    role="Technology Researcher",
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
    instructions=dedent("""
        You specialize in business and market analysis.
        - Focus on companies, markets, and economic trends
        - Provide actionable business insights
        - Include relevant data and statistics
    """).strip(),
)

# Create research team with tools and context management
research_team = Team(
    name="Research Team",
    model=OpenAIChat("gpt-4o"),
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
    db=SqliteDb(db_file="tmp/research_team.db"),
    session_id="research_session",
    add_history_to_context=True,
    num_history_runs=6,  # Load last 6 research queries
    max_tool_calls_from_history=3,  # Keep only last 3 research results
    markdown=True,
    show_members_responses=True,
)

if __name__ == "__main__":
    research_team.print_response(
        "What are the latest developments in AI agents? Which companies dominate the market? Find the latest news and reports on the companies.",
        stream=True,
    )
    research_team.print_response(
        "How is the tech market performing this quarter? How about last year? Find the latest news and reports on Mag 7.",
        stream=True,
    )
    research_team.print_response(
        "What are the trends in LLM applications for enterprises? Find the latest news and reports on the trends.",
        stream=True,
    )
    research_team.print_response(
        "What companies are leading in AI infrastructure? Find reports on the companies and their products.",
        stream=True,
    )
