"""
Cerebras Request Parameters
===========================

Configure request parameters that the native Cerebras model forwards to the
Cerebras chat completions API.

Use ``max_tokens`` only as a compatibility alias, and do not set it together
with ``max_completion_tokens``. Additional supported fields include
``parallel_tool_calls``, ``tool_choice``, ``service_tier``,
``prompt_cache_key``, and ``prediction``.
"""

from agno.agent import Agent
from agno.models.cerebras import Cerebras

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Cerebras(
        id="gpt-oss-120b",
        max_completion_tokens=256,
        reasoning_effort="none",
        temperature=0.2,
        top_p=0.9,
        seed=42,
        stop=["END"],
        frequency_penalty=0.1,
        presence_penalty=0.1,
        logprobs=True,
        top_logprobs=3,
        user="agno-cookbook",
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("Explain why deterministic sampling is useful. End with END")
