"""
This cookbook shows how to extend caching time for agents using cache with Anthropic models.

You can check more about extended prompt caching with Anthropic models here: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching#1-hour-cache-duration-beta
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.anthropic import Claude
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
        betas=["extended-cache-ttl-2025-04-11"],
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

if response and response.metrics:
    print(f"First run cache write tokens = {response.metrics.cache_write_tokens}")

# Second run - this will use the cached system prompt
response = agent.run(
    "What are the key principles of clean code and how do I apply them in Python?"
)
if response and response.metrics:
    print(f"Second run cache read tokens = {response.metrics.cache_read_tokens}")
