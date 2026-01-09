"""
Full context compression example.

This example demonstrates how to use the `compress_context` flag to automatically
compress the entire conversation context when the token limit is hit. This is useful
for long-running conversations where you want to maintain continuity while staying
within token limits.

Key features:
- `compress_context=True` enables full context compression
- `compression_manager` with `compress_token_limit` sets the threshold

When the token count exceeds the limit, the conversation is summarized into a
structured format that preserves key facts, data, and task progress.
"""

from agno.agent import Agent
from agno.compression import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.parallel import ParallelTools

compression_manager = CompressionManager(
    compress_context=True,
    compress_token_limit=15000,
)

agent = Agent(
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[DuckDuckGoTools(), ParallelTools()],
    description="A research assistant that can search the web for information",
    instructions="Use the search tools to find the latest information. Be thorough and cite sources.",
    db=SqliteDb(db_file="tmp/full_compression.db"),
    session_id="full_compression",
    compression_manager=compression_manager,
    add_history_to_context=True,
    num_history_runs=5,
)

agent.print_response(
    "Research the latest developments in AI model reasoning capabilities. Focus on o1, Claude, and Gemini, Grok, deepseek, mistral, etc.",
    stream=True,
)

agent.print_response(
    "Now compare the pricing of these models for enterprise use. And also consumer offerings",
    stream=True,
)

agent.print_response(
    "Based on your research, which model would you recommend for a startup building a coding assistant?",
    stream=True,
)
