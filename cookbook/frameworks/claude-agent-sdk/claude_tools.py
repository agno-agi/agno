"""
ClaudeAgent: Stream a Code Review
==================================
Inspect the bundled shipping project with a streamed response and tool display.

The harness owns tool execution; print_response displays progress and tool calls.
It returns the final RunOutput, whose tools retain the full results. Expect
shipping fees of 8, 0 and 0 dollars, including the boundary order.
This reads files; it does not demonstrate edits, approvals or tenant isolation.
See README.md for setup and permission details.
"""

from pathlib import Path

from agno.agents.claude import ClaudeAgent

# ---------------------------------------------------------------------------
# Configure the Workspace
# ---------------------------------------------------------------------------
workspace = Path(__file__).resolve().parents[1] / "sample_project"
prompt = "Read shipping.py and orders.json with your file or shell tools. Explain the shipping fee for each order and the boundary condition. Do not modify files or use the network."

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = ClaudeAgent(
    id="claude-tools",
    model="claude-sonnet-5-5",
    cwd=str(workspace),
    allowed_tools=["Read"],
    permission_mode="dontAsk",
    tools=["Read"],
    setting_sources=[],
    strict_mcp_config=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result = agent.print_response(prompt, stream=True)
