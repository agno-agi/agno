"""
Multi-block prompt caching with per-block TTL and tool caching.

Demonstrates two Anthropic caching features:
1. Per-block TTL: Split system prompts into static (cached) and dynamic (uncached)
   blocks with independent TTLs. The static block uses a 1h extended TTL so it
   survives across longer conversations, while the dynamic block is never cached.
2. Tool caching: Opt in to caching tool definitions by setting cache_tools=True.
   Anthropic caches all tools as a prefix when cache_control is on the last tool.

Blocks live on the Claude model (not on Agent.system_message) because this is a
Claude-specific feature. They are appended after the agent-built system prompt,
which itself becomes the first cached block when cache_system_prompt=True. This
preserves your agent's description, instructions, and tool hints while letting
you add per-request static or dynamic blocks with their own cache settings.

Note on mixed TTLs: Anthropic requires any 1h cached block to appear before any
5m cached block in the request. Because the agent-built block comes first and
inherits the model-level TTL, you must set extended_cache_time=True whenever
any SystemPromptBlock uses ttl="1h". Otherwise the request would be
5m (agent) -> 1h (block), which the API rejects. Agno validates this at
assembly time with a clear error.

Docs: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
"""

from datetime import datetime

from agno.agent import Agent
from agno.models.anthropic import Claude, SystemPromptBlock
from agno.tools.duckduckgo import DuckDuckGoTools

blocks = [
    # Static instructions, cached for 1 hour (2x cost but survives much longer)
    SystemPromptBlock(
        text=(
            "You are a senior software architect. You give concise, opinionated "
            "advice grounded in real-world experience. Prefer battle-tested "
            "patterns over trendy abstractions. When recommending tools or "
            "libraries, explain the trade-offs honestly."
        ),
        cache=True,
        ttl="1h",
    ),
    # Dynamic per-user context, never cached (changes every request)
    SystemPromptBlock(
        text=f"The user is on the Enterprise plan and prefers Python examples. Current time: {datetime.now().isoformat()}",
        cache=False,
    ),
]

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-5-20250929",
        cache_system_prompt=True,
        # Required when any SystemPromptBlock uses ttl="1h": the agent-built
        # block would otherwise be cached at 5m and precede a 1h block, which
        # violates Anthropic's mixed-TTL ordering rule.
        extended_cache_time=True,
        cache_tools=True,
        system_prompt_blocks=blocks,
    ),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# First run creates the cache
response = agent.run("What's the best way to structure a large FastAPI project?")
if response and response.metrics:
    print(
        f"Run 1 - cache write: {response.metrics.cache_write_tokens}, cache read: {response.metrics.cache_read_tokens}"
    )

# Second run reads from cache
response = agent.run("How should I handle database migrations in that setup?")
if response and response.metrics:
    print(
        f"Run 2 - cache write: {response.metrics.cache_write_tokens}, cache read: {response.metrics.cache_read_tokens}"
    )
