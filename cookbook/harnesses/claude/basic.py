"""
ClaudeAgent: First Run
=======================
Run one shipping-policy question and print the answer, run ID and terminal status.

No Agno database is configured. This proves a model round trip, not session
recovery. Compare native_sdk.py for the same prompt without the Agno adapter.
Try changing the order amount in the prompt. See README.md for setup.
"""

from pathlib import Path

from agno.agents.claude import ClaudeAgent

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
    model="claude-sonnet-5-5",
    cwd=str(workspace),
    tools=[],
    setting_sources=[],
    strict_mcp_config=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(prompt, stream=False)
