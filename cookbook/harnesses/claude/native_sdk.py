"""
Claude SDK: The Same First Run
=============================
Run the basic.py prompt directly through the official Claude Agent SDK.

The SDK yields native messages, ending with a ResultMessage. Agno's basic.py
returns a RunOutput instead. Neither example configures an Agno database.
See README.md for authentication, the comparison and the official reference.
"""

import asyncio
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

# ---------------------------------------------------------------------------
# Create SDK Options
# ---------------------------------------------------------------------------
workspace = Path(__file__).resolve().parents[1] / "sample_project"
prompt = "Shipping costs 8 dollars below 100 dollars and is free at or above 100 dollars. What is the shipping fee for an order of exactly 100 dollars? Answer in one sentence. Do not use tools."
options = ClaudeAgentOptions(
    model="claude-sonnet-5-5",
    cwd=str(workspace),
    tools=[],
    setting_sources=[],
    strict_mcp_config=True,
    max_turns=2,
    max_budget_usd=0.5,
)


# ---------------------------------------------------------------------------
# Run the SDK
# ---------------------------------------------------------------------------
async def main() -> None:
    result = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result = message
    assert result is not None, "No SDK result received"
    assert not result.is_error and result.subtype == "success", result
    assert result.result, "The SDK completed without an answer"
    print(result.result)
    print(f"Claude session: {result.session_id} | Status: {result.subtype}")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=120))
