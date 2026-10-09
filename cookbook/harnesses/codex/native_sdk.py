"""
Codex SDK: The Same First Run
============================
Run the basic.py prompt directly through the official Codex Python SDK.

The SDK exposes threads and turns. Agno's basic.py returns a RunOutput instead.
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
        result = await thread.run(prompt, effort=ReasoningEffort.low)
        assert result.status.value == "completed", result
        assert result.final_response, "The SDK completed without an answer"
        print(result.final_response)
        print(f"Codex thread: {thread.id} | Status: {result.status.value}")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=120))
