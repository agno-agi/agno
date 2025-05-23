"""
This cookbook shows how to use prompt caching with Agents using Anthropic models, to catch the system prompt passed to the model.

This can significantly reduce processing time and costs.
Use it when working with a static and large system prompt.

You can check more about prompt caching with Anthropic models here: https://docs.anthropic.com/en/docs/prompt-caching
"""

from agno.agent import Agent, RunResponse  # noqa
from agno.models.anthropic import Claude

# Update this string with the actual contents of the book (or any other book!)
system_message = """
        You are an AI assistant specialized in literature, specifically in 'Pride and Prejudice'.
        You have the entire contents of the book here: <entire contents of 'Pride and Prejudice'>
        """

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
        cache_system_prompt=True,  # Activate prompt caching for Anthropic to cache the system prompt
    ),
    system_message=system_message,
    markdown=True,
)


response = agent.run("Talk to me about the characters of 'Pride and Prejudice'")
print(f"Cache creation input tokens: {response.metrics['cache_creation_input_tokens']}")  # type: ignore
