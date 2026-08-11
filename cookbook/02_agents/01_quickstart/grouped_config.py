"""
Grouped Config Parameters
=============================

Configure related agent settings as a group instead of individual flat
parameters. Each config object from agno.config bundles one cluster of
settings: HistoryConfig for chat history, ReasoningConfig for reasoning,
RetryConfig for retries, and so on.

The flat parameters remain fully supported. Passing a config object is
equivalent to passing the corresponding flat parameters, and a plain
boolean still works as a simple on/off switch.
"""

from agno.agent import Agent
from agno.config import HistoryConfig, ReasoningConfig, RetryConfig
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# history=HistoryConfig(...) replaces add_history_to_context=True,
# num_history_runs=5, search_past_sessions=True.
# reasoning=ReasoningConfig(...) replaces reasoning=True, reasoning_max_steps=5.
# retry=RetryConfig(...) replaces retries=2, exponential_backoff=True.
agent = Agent(
    name="Grouped Config Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    history=HistoryConfig(num_runs=5, search_past_sessions=True),
    reasoning=ReasoningConfig(max_steps=5),
    retry=RetryConfig(retries=2, exponential_backoff=True),
)

# ---------------------------------------------------------------------------
# Inspect Resolved Settings
# ---------------------------------------------------------------------------
# Config objects resolve to the same flat attributes the flat parameters set.
print("add_history_to_context:", agent.add_history_to_context)
print("num_history_runs:", agent.num_history_runs)
print("search_past_sessions:", agent.search_past_sessions)
print("reasoning:", agent.reasoning)
print("reasoning_max_steps:", agent.reasoning_max_steps)
print("retries:", agent.retries)
print("exponential_backoff:", agent.exponential_backoff)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What are the trade-offs of caching aggressively?", stream=True
    )
