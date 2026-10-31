"""
Claude SDK: The Same First Run
=============================
Run the claude_basic.py prompt directly through the official Claude Agent SDK.

The SDK yields native messages, ending with a ResultMessage. Agno's claude_basic.py
returns a RunOutput instead. Neither example configures an Agno database.
See README.md for authentication, the comparison and the official reference.
"""

import asyncio
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from claude_agent_sdk.types import StreamEvent

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
    include_partial_messages=True,
)


# ---------------------------------------------------------------------------
# Run the SDK
# ---------------------------------------------------------------------------
async def main() -> None:
    result = None
    streamed_text = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, StreamEvent):
            if message.event.get("type") == "content_block_delta":
                delta = message.event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    streamed_text.append(text)
                    print(text, end="", flush=True)
        elif isinstance(message, ResultMessage):
            result = message
    assert result is not None, "No SDK result received"
    assert not result.is_error and result.subtype == "success", result
    assert result.result, "The SDK completed without an answer"
    assert "".join(streamed_text), "No streamed text received"
    print(f"\nClaude session: {result.session_id} | Status: {result.subtype}")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=120))
