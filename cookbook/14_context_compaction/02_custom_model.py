"""
Custom Compaction Model
=======================

Use a cheaper model for generating compaction summaries while keeping the main
agent on a more capable model. The compaction model only generates summaries,
so it can be smaller and faster.

This is useful when:
- Your main agent uses an expensive model (GPT-4, Claude Opus)
- You want to minimize compaction costs
- Summary quality doesn't need to match response quality
"""

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Cheap model for summaries
compaction_manager = CompactionManager(
    model=OpenAIChat(id="gpt-4.1-mini"),  # Cheap model for summaries
    compact_context=True,
    compact_context_message_limit=6,
    compact_context_keep_recent=2,
    compact_context_preserve_user_budget=10000,
)

# More capable model for responses
agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    compaction_manager=compaction_manager,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Agent configured with:")
    print("  Main model: gpt-4.1")
    print("  Compaction model: gpt-4.1-mini")
    print(f"  Message limit: {compaction_manager.compact_context_message_limit}")
    print(f"  Keep recent: {compaction_manager.compact_context_keep_recent}")
    print()

    response = agent.run(
        "Explain the benefits of using separate models for compression."
    )
    print(response.content)
