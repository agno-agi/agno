"""
This cookbook shows how to pre-warm the Anthropic prompt cache before the first
real request, so the first user interaction does not pay the cache-miss latency.

prewarm() sends a max_tokens=0 request that writes the system prompt into the
cache without generating any output. A later agent.run() with the same system
prompt then reads from the warm cache, improving time-to-first-token.

Re-warm within the cache TTL (5 minutes by default) to keep the cache alive.

You can check more about prompt caching with Anthropic models here:
https://docs.anthropic.com/en/docs/prompt-caching
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.message import Message
from agno.utils.media import download_file

# ---------------------------------------------------------------------------
# Create model and pre-warm the cache
# ---------------------------------------------------------------------------

# Load an example large system message from S3. A large, static prompt like
# this is the ideal candidate for pre-warming.
txt_path = Path(__file__).parent.joinpath("system_prompt.txt")
download_file(
    "https://agno-public.s3.amazonaws.com/prompts/system_promt.txt",
    str(txt_path),
)
system_message = txt_path.read_text()

# cache_system_prompt=True is required - prewarm needs a cache_control breakpoint.
model = Claude(id="claude-sonnet-4-5", cache_system_prompt=True)

# Pre-warm the cache before any user traffic arrives. This fires a max_tokens=0
# request that writes the system prompt into the cache without generating output.
prewarm_metrics = model.prewarm(
    messages=[Message(role="system", content=system_message)]
)
if prewarm_metrics:
    print(f"Pre-warm cache write tokens = {prewarm_metrics.cache_write_tokens}")

# The first real run already reads from the warm cache.
agent = Agent(model=model, system_message=system_message, markdown=True)
response = agent.run("Explain the difference between REST and GraphQL APIs")
if response and response.metrics:
    print(f"First run cache read tokens = {response.metrics.cache_read_tokens}")

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
