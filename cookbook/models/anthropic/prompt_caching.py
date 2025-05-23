"""
This cookbook shows how to use prompt caching with Agents using Anthropic models, to catch the system prompt passed to the model.

This can significantly reduce processing time and costs.
Use it when working with a static and large system prompt.

You can check more about prompt caching with Anthropic models here: https://docs.anthropic.com/en/docs/prompt-caching
"""

from agno.agent import Agent, RunResponse  # noqa
from agno.models.anthropic import Claude

# Update this string with the actual contents of the book
system_prompt = """
        You are an AI assistant specialized in literature, specifically in 'Pride and Prejudice'.
        You have the entire contents of the book here: <entire contents of 'Pride and Prejudice'>
        """

agent = Agent(
    model=Claude(
        id="claude-3-5-sonnet-20241022",
        system_prompt=system_prompt,
        cache_system_prompt=True,  # Activate prompt caching for Anthropic to cache the system prompt
    ),
    markdown=True,
)


response = agent.run("Talk to me about the characters of 'Pride and Prejudice'")
print(f"Cached tokens: {response.metrics['cached_tokens']}")  # type: ignore
