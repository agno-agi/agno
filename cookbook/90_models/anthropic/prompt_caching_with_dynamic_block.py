"""
Augment the agent-built system prompt with a dynamic per-request block.

The Agent's description + instructions are assembled into the first system
block and cached automatically when cache_system_prompt=True. A
SystemPromptBlock appended after can carry dynamic content without
invalidating the cached prefix, as long as cache=False on the dynamic
block.

Pass system_prompt_blocks as a callable to have it evaluated on every
request — the right pattern when the dynamic text (timestamp, user
identity, session state) must be fresh per call. The callable runs inside
Claude._build_system with no arguments, so close over whatever state you
need.

Docs: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
"""

from datetime import datetime

from agno.agent import Agent
from agno.models.anthropic import Claude, SystemPromptBlock


def build_request_blocks() -> list[SystemPromptBlock]:
    # Evaluated per request: the timestamp (and any other per-request context)
    # stays fresh without mutating the model or reinstantiating the agent.
    return [
        SystemPromptBlock(
            text=(
                f"Current server time: {datetime.now().isoformat()}. "
                "The user is on the Enterprise plan and prefers Python examples."
            ),
            cache=False,
        )
    ]


agent = Agent(
    model=Claude(
        id="claude-sonnet-4-5-20250929",
        cache_system_prompt=True,
        system_prompt_blocks=build_request_blocks,
    ),
    description=(
        "You are an expert software architect who gives concise, opinionated "
        "advice grounded in real-world experience. You prefer battle-tested "
        "patterns over trendy abstractions."
    ),
    instructions=[
        "Answer in two to four paragraphs.",
        "When comparing options, list the trade-offs honestly.",
        "If you do not know the answer, say so plainly.",
    ],
    markdown=True,
)

# First run writes the cache on the agent-built system block
response = agent.run("How should I structure a large FastAPI application?")
if response and response.metrics:
    print(
        f"Run 1 - cache write: {response.metrics.cache_write_tokens}, "
        f"cache read: {response.metrics.cache_read_tokens}"
    )

# Second run reads the cached prefix. build_request_blocks runs again so the
# dynamic timestamp refreshes, but because that block is cache=False the
# prefix before it stays stable and cache-hot.
response = agent.run("How should I handle background jobs in that setup?")
if response and response.metrics:
    print(
        f"Run 2 - cache write: {response.metrics.cache_write_tokens}, "
        f"cache read: {response.metrics.cache_read_tokens}"
    )
