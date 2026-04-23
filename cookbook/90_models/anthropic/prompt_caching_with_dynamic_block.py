"""
Augment the agent-built system prompt with a dynamic per-request block.

The Agent's description + instructions are assembled into the first system
block and cached automatically when cache_system_prompt=True. Any
SystemPromptBlock on the Claude model is appended as an additional block,
with its own cache setting.

This is the common case: keep your normal agent description/instructions
(which are static and cache well), and add a small dynamic block for
per-request context that would otherwise invalidate the cached prefix.

Docs: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
"""

from datetime import datetime

from agno.agent import Agent
from agno.models.anthropic import Claude, SystemPromptBlock


def make_agent() -> Agent:
    # Dynamic block rebuilt on every process start. cache=False so Anthropic
    # does not try to cache text that will be different next request.
    dynamic_context = SystemPromptBlock(
        text=(
            f"Current server time: {datetime.now().isoformat()}. "
            "The user is on the Enterprise plan and prefers Python examples."
        ),
        cache=False,
    )

    return Agent(
        model=Claude(
            id="claude-sonnet-4-5-20250929",
            cache_system_prompt=True,
            system_prompt_blocks=[dynamic_context],
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


agent = make_agent()

# First run writes the cache on the agent-built system block
response = agent.run("How should I structure a large FastAPI application?")
if response and response.metrics:
    print(
        f"Run 1 - cache write: {response.metrics.cache_write_tokens}, "
        f"cache read: {response.metrics.cache_read_tokens}"
    )

# Second run reads the cached prefix, even though the dynamic block is not cached
response = agent.run("How should I handle background jobs in that setup?")
if response and response.metrics:
    print(
        f"Run 2 - cache write: {response.metrics.cache_write_tokens}, "
        f"cache read: {response.metrics.cache_read_tokens}"
    )
