import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

# Create specialized agents
tech_specialist = Agent(
    name="Tech Specialist",
    role="Technology Researcher",
    model=OpenAIChat(id="gpt-5-mini"),
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
    model=OpenAIChat(id="gpt-4.1"),
    instructions=dedent("""
        You specialize in business and market analysis.
        - Focus on companies, markets, and economic trends
        - Provide actionable business insights
        - Include relevant data and statistics
    """).strip(),
)

research_team = Team(
    name="Research Team",
    model=OpenAIChat(id="gpt-5-mini"),
    members=[tech_specialist, business_analyst],
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
        - Choose the right specialist based on the topic for analysis (tech vs business)
        - Combine your research with specialist analysis
        - Provide comprehensive, well-sourced responses
    """).strip(),
    db=SqliteDb(db_file="tmp/research_team2.db"),
    markdown=True,
    show_members_responses=True,
    compress_tool_results=True,
)


async def main():
    await research_team.aprint_response(
        "What are the latest developments in AI agents? Which companies dominate the market? Find the latest news and reports on the companies.",
        stream=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
