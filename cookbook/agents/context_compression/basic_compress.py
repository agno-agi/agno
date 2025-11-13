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

# Create agent with custom context manager
agent = Agent(
    name="Competitive Intelligence Agent",
    # model=AwsBedrock(
    #     id="arn:aws:bedrock:us-east-1:386435111151:inference-profile/global.anthropic.claude-sonnet-4-20250514-v1:0"
    # ),
    # model="google:gemini-2.5-pro",
    # model=Gemini(id="gemini-2.5-pro", vertexai=True),
    # model=DeepSeek(id="deepseek-reasoner"),
    model="openai:gpt-4o",
    tools=[DuckDuckGoTools()],
    description="Specialized in tracking competitor activities",
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
