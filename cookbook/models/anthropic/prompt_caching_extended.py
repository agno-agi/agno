"""
This cookbook shows how to extend caching time for agents using cache with Anthropic models.

You can check more about extended prompt caching with Anthropic models here: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching#1-hour-cache-duration-beta
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.utils.media import download_file

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
        cache_system_prompt=True,
        extended_cache_time=True,
    ),
    system_message=system_message,
    markdown=True,
)

response = agent.run(
    "Explain the difference between REST and GraphQL APIs with examples"
)
print(f"First run cache write tokens = {response.metrics['cache_write_tokens']}")

response = agent.run(
    "What are the key principles of clean code and how do I apply them in Python?"
)
print(f"Second run cache read tokens = {response.metrics['cached_tokens']}")
