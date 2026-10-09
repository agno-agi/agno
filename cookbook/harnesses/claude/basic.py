"""
ClaudeAgent: First Run
=======================
Run one shipping-policy question and inspect the Agno RunOutput.

No Agno database is configured. This proves a model round trip, not session
recovery. Compare native_sdk.py for the same prompt without the Agno adapter.
Try changing the order amount in the prompt. See README.md for setup.
"""

import os
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

# ---------------------------------------------------------------------------
# Configure the Example
# ---------------------------------------------------------------------------
workspace = Path(__file__).resolve().parents[1] / "sample_project"
prompt = "Shipping costs 8 dollars below 100 dollars and is free at or above 100 dollars. What is the shipping fee for an order of exactly 100 dollars? Answer in one sentence. Do not use tools."

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = ClaudeAgent(
    id="claude-basic",
    model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
    cwd=str(workspace),
    max_turns=2,
    max_budget_usd=0.5,
    options_kwargs={"tools": [], "setting_sources": [], "strict_mcp_config": True},
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result = agent.run(prompt)
    assert isinstance(result, RunOutput)
    assert result.status == RunStatus.completed, result.content
    assert result.content, "The harness completed without an answer"
    print(result.content)
    print(f"Run: {result.run_id} | Status: {result.status.value}")
