"""
ClaudeAgent: Stream a Code Review
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

from agno.agents.claude import ClaudeAgent
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

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
    model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
    cwd=str(workspace),
    max_turns=6,
    max_budget_usd=0.5,
    allowed_tools=["Read"],
    permission_mode="dontAsk",
    options_kwargs={
        "tools": ["Read"],
        "setting_sources": [],
        "strict_mcp_config": True,
    },
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result = None
    for event in agent.run(prompt, stream=True, yield_run_output=True):
        if isinstance(event, RunOutput):
            result = event
        elif event.event == "RunContent":
            print(event.content or "", end="", flush=True)
        elif event.event in ("ToolCallStarted", "ToolCallCompleted"):
            print(f"\n{event.event}: {event.tool.tool_name}")
            if event.event == "ToolCallCompleted":
                print(event.tool.result)
        elif event.event == "RunError":
            raise RuntimeError(event.content)

    assert result is not None, "No terminal RunOutput received"
    assert result.status == RunStatus.completed, result.content
    assert result.content, "The harness completed without an answer"
    assert result.tools, "Expected the harness to inspect the fixture using tools"
    assert any(tool.result and not tool.tool_call_error for tool in result.tools), (
        "No successful tool result"
    )
    print(f"\nRun: {result.run_id} | Status: {result.status.value}")
