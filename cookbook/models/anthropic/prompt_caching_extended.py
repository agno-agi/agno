"""
This cookbook shows how to extend caching time for agents using cache with Anthropic models.

You can check more about extended prompt caching with Anthropic models here: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching#1-hour-cache-duration-beta
"""

from agno.agent import Agent
from agno.models.anthropic import Claude

system_prompt = """
        You are an AI assistant specialized in literature, specifically in 'Pride and Prejudice'.
        You have the entire contents of the book here: <entire contents of 'Pride and Prejudice'>
        """

agent = Agent(
    model=Claude(
        id="claude-3-5-sonnet-20241022",
        system_prompt=system_prompt,
        cache_system_prompt=True,  # Activate prompt caching for Anthropic to cache the system prompt
        extended_cache_time=True,  # Extend the cache time from the default to 1 hour
    ),
    markdown=True,
)


response = agent.run("Talk to me about the characters of 'Pride and Prejudice'")
print(f"Cached tokens: {response.metrics['cached_tokens']}")  # type: ignore
