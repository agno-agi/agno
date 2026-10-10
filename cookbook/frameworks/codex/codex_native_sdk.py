"""
Codex SDK: The Same First Run
============================
Run the codex_basic.py prompt directly through the official Codex Python SDK.

The SDK exposes threads and turns. Agno's codex_basic.py returns a RunOutput instead.
This example uses the SDK's bundled app-server and existing authentication.
See README.md for setup, the comparison and the official reference.
"""

import asyncio
import os
from pathlib import Path

from openai_codex import ApprovalMode, AsyncCodex, Sandbox
from openai_codex.types import ReasoningEffort

# ---------------------------------------------------------------------------
# Create SDK Configuration
# ---------------------------------------------------------------------------
workspace = Path(__file__).resolve().parents[1] / "sample_project"
prompt = "Shipping costs 8 dollars below 100 dollars and is free at or above 100 dollars. What is the shipping fee for an order of exactly 100 dollars? Answer in one sentence. Do not use tools."
model = os.getenv("CODEX_MODEL", "gpt-5.6-luna")


# ---------------------------------------------------------------------------
# Run the SDK
# ---------------------------------------------------------------------------
async def main() -> None:
    async with AsyncCodex() as codex:
        thread = await codex.thread_start(
            model=model,
            cwd=str(workspace),
            sandbox=Sandbox.read_only,
            approval_mode=ApprovalMode.deny_all,
        )
        turn = await thread.turn(prompt, effort=ReasoningEffort.low)
        completed = None
        streamed_text = []
        async for event in turn.stream():
            if event.method == "item/agentMessage/delta":
                streamed_text.append(event.payload.delta)
                print(event.payload.delta, end="", flush=True)
            elif event.method == "turn/completed":
                completed = event.payload.turn
        assert completed is not None, "No terminal turn received"
        assert completed.status.value == "completed", completed
        assert "".join(streamed_text), "No streamed text received"
        print(f"\nCodex thread: {thread.id} | Status: {completed.status.value}")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=120))
