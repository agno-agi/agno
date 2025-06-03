"""
Enhanced Prompt Caching Example for Claude Models

This example demonstrates the comprehensive prompt caching features available
with Claude models in Agno, including:
- System message caching
- Tool definition caching
- Message content caching
- 5-minute and 1-hour cache TTL options
- Usage metrics tracking

For more information about prompt caching, see:
https://docs.anthropic.com/en/api/prompt-caching
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.media import download_file

# Load an example large system message from S3. A large prompt like this would benefit from caching.
txt_path = Path(__file__).parent.joinpath("system_promt.txt")
download_file(
    "https://agno-public.s3.amazonaws.com/prompts/system_promt.txt",
    str(txt_path),
)
system_message = txt_path.read_text()

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
        default_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"},
        system_prompt=system_message,
        cache_system_prompt=True,  # Activate prompt caching for Anthropic to cache the system prompt
        extended_cache_time=True,  # Extend the cache time from the default to 1 hour
    ),
    system_message=system_message,
    markdown=True,
)


# First run - this will create the cache
response = agent.run(
    "Explain the difference between REST and GraphQL APIs with examples"
)
print(f"First run cache write tokens = {response.metrics['cache_write_tokens']}")  # type: ignore

# Second run - this will use the cached system prompt
response = agent.run(
    "What are the key principles of clean code and how do I apply them in Python?"
)
print(f"Second run cache read tokens = {response.metrics['cached_tokens']}")  # type: ignore


def basic_system_caching_example():
    """Example demonstrating basic system message caching."""
    print("=== Basic System Message Caching ===")

    large_system_prompt = (
        """
    You are an expert literary analyst with extensive knowledge of classic literature.
    Your expertise covers themes, character development, narrative techniques, and historical context.
    
    When analyzing works, consider:
    1. Historical and cultural context of the time period
    2. Author's biographical influences on the work
    3. Literary movements and schools of thought
    4. Symbolism and metaphorical elements
    5. Character archetypes and development
    6. Narrative structure and techniques
    7. Themes and philosophical implications
    8. Language, style, and rhetorical devices
    9. Reception and critical interpretations over time
    10. Influence on subsequent literature and culture
    
    Always provide detailed, well-reasoned analysis with specific examples from the text.
    """
        * 20
    )  # Make it large enough to benefit from caching

    # Create agent with system prompt caching enabled
    agent = Agent(
        model=Claude(
            id="claude-3-5-sonnet-20241022",
            cache_system_prompt=True,  # Enable system message caching
            cache_ttl="5m",  # 5-minute cache (default)
        ),
        description=large_system_prompt,
        show_tool_calls=True,
    )

    # First call - should create cache
    print("First call (creates cache):")
    response1 = agent.run("Analyze the theme of pride in Pride and Prejudice")
    print(f"Usage: {response1.usage}")
    print(f"Response length: {len(response1.content)}")

    # Second call - should use cache
    print("\nSecond call (uses cache):")
    response2 = agent.run(
        "What is the significance of Mr. Darcy's character development?"
    )
    print(f"Usage: {response2.usage}")
    print(f"Response length: {len(response2.content)}")


def extended_cache_example():
    """Example demonstrating 1-hour cache duration."""
    print("\n=== Extended Cache Duration (1 hour) ===")

    large_context = (
        """
    Complete text of a large document that you want to analyze multiple times...
    """
        * 100
    )  # Simulate a large document

    agent = Agent(
        model=Claude(
            id="claude-3-5-sonnet-20241022",
            enable_prompt_caching=True,
            cache_ttl="1h",  # 1-hour cache duration
        ),
        description=f"You are a document analyzer. Here is the document to analyze:\n\n{large_context}",
    )

    response = agent.run("Summarize the key themes in this document")
    print(f"Usage with 1h cache: {response.usage}")


def tool_caching_example():
    """Example demonstrating tool definition caching."""
    print("\n=== Tool Definition Caching ===")

    # Create multiple tools to cache
    tools = [DuckDuckGoTools()]

    agent = Agent(
        model=Claude(
            id="claude-3-5-sonnet-20241022",
            cache_tool_definitions=True,  # Enable tool caching
            enable_prompt_caching=True,  # Also cache system prompt
        ),
        tools=tools,
        description="You are a research assistant with access to web search tools.",
    )

    # First call with tools
    print("First call with tools (creates cache):")
    response1 = agent.run("Search for recent developments in AI")
    print(f"Usage: {response1.usage}")

    # Second call - tools should be cached
    print("\nSecond call (cached tools):")
    response2 = agent.run("Find information about climate change solutions")
    print(f"Usage: {response2.usage}")


def message_caching_example():
    """Example demonstrating message content caching."""
    print("\n=== Message Content Caching ===")

    # Long conversation context that we want to cache
    conversation_history = [
        "Tell me about the history of artificial intelligence",
        "What were the key milestones in AI development?",
        "How has machine learning evolved over time?",
        "What are the current challenges in AI research?",
    ]

    agent = Agent(
        model=Claude(
            id="claude-3-5-sonnet-20241022",
            cache_messages={
                "cache_last": True,  # Cache the last message in conversation
                "ttl": "5m",  # Cache for 5 minutes
            },
        ),
        description="You are an AI historian providing detailed information about AI development.",
    )

    # Simulate a conversation
    for question in conversation_history:
        print(f"\nUser: {question}")
        response = agent.run(question)
        print(f"Usage: {response.usage}")
        print(f"Assistant: {response.content[:100]}...")


def comprehensive_caching_example():
    """Example combining all caching features."""
    print("\n=== Comprehensive Caching Example ===")

    large_knowledge_base = (
        """
    You have access to a comprehensive knowledge base about renewable energy technologies.
    This includes detailed information about:
    - Solar power systems and photovoltaic technology
    - Wind energy and turbine engineering
    - Hydroelectric power generation
    - Geothermal energy systems
    - Biomass and biofuel technologies
    - Energy storage solutions
    - Grid integration challenges
    - Economic and environmental impacts
    - Policy and regulatory frameworks
    - Future innovations and research directions
    """
        * 50
    )  # Large knowledge base

    agent = Agent(
        model=Claude(
            id="claude-3-5-sonnet-20241022",
            # Enable all caching features
            enable_prompt_caching=True,
            cache_system_prompt=True,
            cache_tool_definitions=True,
            cache_messages={
                "cache_last": True,
                "ttl": "1h",  # Use 1-hour cache for long conversations
            },
            cache_ttl="1h",  # Default 1-hour cache
        ),
        tools=[DuckDuckGoTools()],
        description=large_knowledge_base,
    )

    queries = [
        "Explain solar panel efficiency improvements",
        "What are the latest wind turbine technologies?",
        "Search for recent battery storage innovations",
        "How does grid integration work with renewables?",
    ]

    for query in queries:
        print(f"\nQuery: {query}")
        response = agent.run(query)
        usage = response.usage

        print(f"Usage metrics:")
        print(f"  Input tokens: {usage.get('input_tokens', 0)}")
        print(f"  Output tokens: {usage.get('output_tokens', 0)}")
        print(f"  Cached tokens: {usage.get('cached_tokens', 0)}")
        print(f"  Cache write tokens: {usage.get('cache_write_tokens', 0)}")

        # Enhanced cache metrics (if available)
        if "5m_write_tokens" in usage:
            print(f"  5m cache writes: {usage['cache_5m_write_tokens']}")
        if "cache_1h_write_tokens" in usage:
            print(f"  1h cache writes: {usage['cache_1h_write_tokens']}")


def cache_performance_analysis():
    """Analyze cache performance and cost savings."""
    print("\n=== Cache Performance Analysis ===")

    # Example showing cost calculation benefits
    baseline_tokens = 10000  # Typical large prompt
    cached_tokens = 9500  # Tokens read from cache
    cache_hit_rate = cached_tokens / baseline_tokens

    # Pricing (example based on Claude 3.5 Sonnet)
    base_price_per_mtok = 3.0  # $3 per million tokens
    cache_read_price_per_mtok = 0.3  # $0.30 per million tokens (0.1x base)
    cache_write_price_per_mtok = 3.75  # $3.75 per million tokens (1.25x base)

    # Cost without caching
    cost_without_cache = (baseline_tokens / 1_000_000) * base_price_per_mtok

    # Cost with caching (first call writes cache, subsequent calls read)
    cache_write_cost = (baseline_tokens / 1_000_000) * cache_write_price_per_mtok
    cache_read_cost = (cached_tokens / 1_000_000) * cache_read_price_per_mtok
    new_tokens_cost = (
        (baseline_tokens - cached_tokens) / 1_000_000
    ) * base_price_per_mtok

    print(f"Cache Performance Metrics:")
    print(f"  Cache hit rate: {cache_hit_rate:.1%}")
    print(f"  Tokens cached: {cached_tokens:,}")
    print(f"  Cost without caching: ${cost_without_cache:.4f}")
    print(
        f"  Cost with caching (after first call): ${cache_read_cost + new_tokens_cost:.4f}"
    )
    print(
        f"  Cost savings per call: ${cost_without_cache - (cache_read_cost + new_tokens_cost):.4f}"
    )
    print(
        f"  Savings percentage: {((cost_without_cache - (cache_read_cost + new_tokens_cost)) / cost_without_cache) * 100:.1f}%"
    )


if __name__ == "__main__":
    print("🚀 Enhanced Claude Prompt Caching Examples")
    print("=" * 50)

    # Set up your ANTHROPIC_API_KEY environment variable before running

    try:
        # Run all examples
        basic_system_caching_example()
        extended_cache_example()
        tool_caching_example()
        message_caching_example()
        comprehensive_caching_example()
        cache_performance_analysis()

        print("\n✅ All caching examples completed successfully!")
        print("\nKey Benefits of Prompt Caching:")
        print("- Up to 90% cost reduction for cached content")
        print("- Significantly faster response times")
        print("- Better rate limit utilization")
        print("- Improved user experience for repetitive tasks")

    except Exception as e:
        print(f"❌ Error running examples: {e}")
        print("Make sure to set your ANTHROPIC_API_KEY environment variable")
