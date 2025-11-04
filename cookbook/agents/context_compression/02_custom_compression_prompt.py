"""Advanced context compression with custom compression prompt.

This example shows how to customize the compression prompt for domain-specific
use cases. Here we optimize compression for competitive intelligence gathering.

Run: `python cookbook/agents/context_compression/02_custom_compression_prompt.py`
"""

from agno.agent import Agent
from agno.context.manager import ContextManager
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

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
    model=OpenAIChat(id="gpt-4o-mini"),  # Use mini model for compression to save costs
    tool_compression_threshold=3,
    tool_compression_instructions=custom_compression_prompt,  # Custom prompt!
)

# Create agent with custom context manager
agent = Agent(
    name="Competitive Intelligence Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    description="Specialized in tracking competitor activities",
    context_manager=context_manager,  # Pass custom context manager
    compress_context=True,
    markdown=True,
    debug_mode=True,
)

print("=" * 80)
print("🎯 CUSTOM COMPRESSION PROMPT EXAMPLE")
print("=" * 80)
print("\nThis agent uses a domain-specific compression prompt optimized for")
print("competitive intelligence gathering.")
print("\nCompression model: gpt-4o-mini (cost-optimized)")
print("Main model: gpt-4o (high-quality research)")
print("=" * 80)

# Research multiple competitors
response = agent.run(
    """Research recent activities (last 3 months) for these AI companies:
    
    1. OpenAI - product launches, partnerships, pricing
    2. Anthropic - new features, enterprise deals, funding
    3. Google DeepMind - research breakthroughs, product releases
    4. Meta AI - open source releases, research papers
    
    For each, find specific actions with dates and numbers.""",
    stream=True,
)

# Show compression effectiveness
if agent.context_manager:
    print("\n" + "=" * 80)
    print("📊 COMPRESSION STATS")
    print("=" * 80)
    print(
        f"Compression model: {agent.context_manager.model.id if agent.context_manager.model else 'None'}"
    )
    print(f"Times compressed: {agent.context_manager.compression_count}")
    print(f"Threshold: {agent.context_manager.tool_compression_threshold} tool results")
    print(
        "\n✅ Custom prompt ensured compressed results focus on actionable intelligence!"
    )
    print("=" * 80)
