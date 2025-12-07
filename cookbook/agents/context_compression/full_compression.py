"""
Full Context Compression Example

This example demonstrates context compression across multiple runs:
- Compression triggers when token count exceeds the limit
- Compressed context persists to database between runs
- Old messages are filtered, keeping only the summary + recent messages

Run: python cookbook/agents/context_compression/full_compression.py
"""

from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.db.sqlite import SqliteDb
from agno.models.google.gemini import Gemini
from agno.tools.duckduckgo import DuckDuckGoTools

# Create compression manager with token limit
compression_manager = CompressionManager(
    model=Gemini(id="gemini-2.0-flash"),  # Use fast model for compression
    compress_context=True,
    compress_context_token_limit=4000,  # Compress when context exceeds this
)

agent = Agent(
    model=Gemini(id="gemini-2.5-flash"),  # Main model for responses
    tools=[DuckDuckGoTools()],
    description="AI research analyst specialized in tracking competitor activities",
    instructions="""You are a thorough research analyst.
    - Use search tools to find the latest information
    - Always cite specific dates, numbers, and sources
    - Make multiple searches to gather comprehensive data
    - Synthesize findings into actionable insights""",
    db=SqliteDb(db_file="tmp/dbs/full_compression.db"),
    compression_manager=compression_manager,
    compress_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    session_id="full_compression",
    debug_mode=True,
)

# Run 1: Complex research task that will trigger compression
print("=" * 80)
print("RUN 1: Initial research task (should trigger compression)")
print("=" * 80 + "\n")

agent.print_response(
    """Research the AI industry comprehensively. I need detailed information on:

1. OpenAI recent news:
   - Latest product launches and features
   - Pricing changes
   - Key partnerships or acquisitions

2. Anthropic updates:
   - Claude model improvements
   - Enterprise features
   - Funding rounds

3. Google AI/DeepMind:
   - Gemini updates
   - Research breakthroughs

For EACH company, search separately and provide specific details with dates.""",
    stream=True,
)

# Run 2: Follow-up question to test context persistence
print("\n" + "=" * 80)
print("RUN 2: Follow-up question (testing memory after compression)")
print("=" * 80 + "\n")

agent.print_response(
    "Based on your research, which company has the most aggressive pricing strategy?",
    stream=True,
)

# Run 3: Another follow-up to test continued context
print("\n" + "=" * 80)
print("RUN 3: Another follow-up (testing continued context)")
print("=" * 80 + "\n")

agent.print_response(
    "What was the most significant research breakthrough you found?",
    stream=True,
)

print("\n" + "=" * 80)
print("Test complete. Check logs for compression events and context persistence.")
print("=" * 80)
