"""DeepL Tools Example

This example demonstrates how to use the DeepLTools toolkit with an AI agent
to translate text between languages using the DeepL API.

Setup:
1. Get a free API key from https://www.deepl.com/pro-api
2. Set the environment variable: export DEEPL_API_KEY="your_api_key"
3. Install the required dependencies: pip install openai

Usage:
    python deepl_tools.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.deepl import DeepLTools

# Create an agent with DeepL tools
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DeepLTools()],
    instructions=[
        "You are a helpful multilingual assistant that can translate text.",
        "When translating, always mention the detected source language.",
        "If the user asks about formality, explain which languages support it.",
    ],
    markdown=True,
)

# Example 1: Basic translation
print("=" * 60)
print("Example 1: Basic translation to German")
print("=" * 60)
agent.print_response(
    "Translate 'Hello, how are you today?' to German",
    stream=True,
)

# Example 2: Translation with formality
print("\n" + "=" * 60)
print("Example 2: Translation with formality (formal)")
print("=" * 60)
agent.print_response(
    "Translate 'Can you help me with this?' to Spanish using formal language",
    stream=True,
)

# Example 3: Get supported languages
print("\n" + "=" * 60)
print("Example 3: List supported target languages")
print("=" * 60)
agent.print_response(
    "What languages can DeepL translate to? List a few examples.",
    stream=True,
)
