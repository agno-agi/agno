"""
This example shows how to customize the compression prompt for domain-specific
use cases. Here we optimize compression for competitive intelligence gathering.

Run: `python cookbook/agents/context_management/tool_call_compression.py`
"""

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

custom_compression_prompt = """You are compressing web search results for a competitive intelligence analyst.

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
    model=OpenAIChat(id="gpt-4o-mini"),
    compress_tool_results_limit=1,
    compress_tool_call_instructions=custom_compression_prompt,  # Custom prompt!
)

agent = Agent(
    model=Gemini(id="gemini-2.5-pro"),
    tools=[DuckDuckGoTools()],
    description="Specialized in tracking competitor activities",
    compression_manager=compression_manager,
    compress_tool_results=True,
    markdown=True,
    db=SqliteDb(db_file="tmp/dbs/competitive_intelligence_agent.db"),
    session_id="competitive_intelligence_agent",
    add_history_to_context=True,
    num_history_runs=6,
    instructions="Use the search tools and always use the latest information and data.",
)

agent.print_response(
    """
    Use the search tools and alwayd for the latest information and data.
    Research recent activities (last 3 months) for these AI companies:
    
    1. OpenAI - product launches, partnerships, pricing
    2. Anthropic - new features, enterprise deals, funding
    3. Google DeepMind - research breakthroughs, product releases
    4. Meta AI - open source releases, research papers
   
    For each, find specific actions with dates and numbers.""",
)

agent.run("What is the latest news about OpenAI?")
agent.run("What is the latest news about Anthropic?")
agent.run("What is the latest news about Google DeepMind?")
agent.run("What is the latest news about Meta AI?")
