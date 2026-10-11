"""
CodexAgent: Stream a Code Review
==================================
Inspect the bundled shipping project and stream text plus tool lifecycle events.

The harness owns tool execution; Agno translates it into RunContent,
ToolCallStarted and ToolCallCompleted events. The final RunOutput retains tool
results. Expect shipping fees of 8, 0 and 0 dollars, including the boundary order.
This reads files; it does not demonstrate edits, approvals or tenant isolation.
See README.md for setup and permission details.
"""

import os
from pathlib import Path

from agno.agents.codex import CodexAgent
from agno.run.base import RunStatus

# ---------------------------------------------------------------------------
# Configure the Workspace
# ---------------------------------------------------------------------------
workspace = Path(__file__).resolve().parents[1] / "sample_project"
prompt = "Read shipping.py and orders.json with your file or shell tools. Explain the shipping fee for each order and the boundary condition. Do not modify files or use the network."

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = CodexAgent(
    id="codex-tools",
    model=os.getenv("CODEX_MODEL", "gpt-5.6-luna"),
    cwd=str(workspace),
    sandbox="read-only",
    approval_mode="deny_all",
    reasoning_effort="low",
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result = agent.print_response(prompt, stream=True)

    assert result.status == RunStatus.completed, result.content
    assert result.content, "The harness completed without an answer"
    assert result.tools, "Expected the harness to inspect the fixture using tools"
    assert any(tool.result and not tool.tool_call_error for tool in result.tools), (
        "No successful tool result"
    )
