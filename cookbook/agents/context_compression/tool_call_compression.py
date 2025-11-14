"""
This example shows how to customize the compression prompt for domain-specific
use cases. Here we optimize compression for competitive intelligence gathering.

Run: `python cookbook/agents/context_management/tool_call_compression.py`
"""

from agno.agent import Agent
from agno.context.manager import ContextManager
from agno.db.sqlite import SqliteDb
from agno.models.aws import AwsBedrock
from agno.models.deepseek import DeepSeek
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.log import log_info

# Custom compression prompt optimized for competitive intelligence
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

# Create context manager with custom compression
context_manager = ContextManager(
    model=OpenAIChat(id="gpt-4o-mini"),
    compress_tool_calls_limit=1,
    tool_compression_instructions=custom_compression_prompt,  # Custom prompt!
)

# Create agent with custom context manager
agent = Agent(
    name="Competitive Intelligence Agent",
    # model=AwsBedrock(
    #     id="arn:aws:bedrock:us-east-1:386435111151:inference-profile/global.anthropic.claude-sonnet-4-20250514-v1:0"
    # ),
    # model="google:gemini-2.5-pro",
    # model=Gemini(id="gemini-2.5-pro", vertexai=True),
    model=DeepSeek(id="deepseek-reasoner"),
    tools=[DuckDuckGoTools()],
    description="Specialized in tracking competitor activities",
    context_manager=context_manager,
    compress_tool_calls=True,
    markdown=True,
    db=SqliteDb(db_file="tmp/dbs/competitive_intelligence_agent_.db"),
    session_id="competitive_intelligence_agent",
    add_history_to_context=True,
    num_history_runs=6,
    instructions="Use the search tools and alwayd for the latest information and data.",
    debug_mode=True,
)


def print_compression_stats(run_response):
    """Print compression statistics from the run."""
    if not run_response or not run_response.messages:
        return

    total_tools = 0
    compressed_tools = 0
    original_size = 0
    compressed_size = 0

    for msg in run_response.messages:
        if msg.role == "tool":
            total_tools += 1
            if msg.compressed_content is not None:
                compressed_tools += 1
                original_size += len(str(msg.content)) if msg.content else 0
                compressed_size += len(msg.compressed_content)

    if compressed_tools > 0:
        ratio = (
            int((1 - compressed_size / original_size) * 100) if original_size > 0 else 0
        )
        log_info("=" * 80)
        log_info(f"   Total tool calls: {total_tools}")
        log_info(f"   Compressed: {compressed_tools}")
        log_info(f"   Original size: {original_size:,} bytes")
        log_info(f"   Compressed size: {compressed_size:,} bytes")
        log_info(f"   Space saved: {ratio}% reduction")
        log_info("=" * 80)
    else:
        log_info(
            f"ℹ️  No compression triggered yet ({total_tools} tool calls, threshold: {context_manager.compress_tool_calls_limit})"
        )


response = agent.run(
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
