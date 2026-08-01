"""
Context Compaction Example

Demonstrates how context compaction works when conversation history exceeds
the configured threshold. The compaction manager summarizes old messages
while preserving recent context and user messages.

Run: .venvs/demo/bin/python cookbook/14_context_compaction/basic_compaction.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# Simple usage: just set context_compaction=True
# Agent auto-creates a compression manager with default settings
agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    context_compaction=True,  # Enable context compaction with defaults
    session_id="context-compaction-demo",
    add_history_to_context=True,
    num_history_runs=50,
)

# Simulate a conversation that would exceed context
print("Starting conversation with context compaction enabled...")
print("=" * 60)

# First message
response = agent.run("Tell me about the history of computers in 3 paragraphs")
print(f"Assistant: {response.content[:200]}...")
print()

# Second message
response = agent.run("Now explain quantum computing in detail")
print(f"Assistant: {response.content[:200]}...")
print()

# Third message
response = agent.run(
    "What are the main differences between classical and quantum computers?"
)
print(f"Assistant: {response.content[:200]}...")
print()

# Check compression stats
print("=" * 60)
print("Compression Manager Stats:")
for key, value in compression_manager.stats.items():
    print(f"  {key}: {value}")
