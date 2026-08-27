"""
Expose a Toolkit as MCP tools
=============================

Pass a Toolkit to MCPServerConfig.tools — it auto-flattens into individual
MCP tools, same as Agent.parse_tools() does internally.

Prerequisites: none (no API key needed for file operations)
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/toolkit_tools.py
Try: connect an MCP client to http://localhost:7777/mcp and call read_file
"""

import tempfile
from pathlib import Path

from agno.os import AgentOS, MCPServerConfig
from agno.tools.workspace import Workspace

# ---------------------------------------------------------------------------
# Create sample workspace
# ---------------------------------------------------------------------------

tmp_dir = tempfile.mkdtemp(prefix="mcp_toolkit_")
sample_dir = Path(tmp_dir)

(sample_dir / "README.md").write_text("# Sample Project\n\nThis is a demo workspace.")
(sample_dir / "main.py").write_text("def hello():\n    return 'Hello, MCP!'\n")
(sample_dir / "utils.py").write_text("def add(a, b):\n    return a + b\n")

# ---------------------------------------------------------------------------
# Create toolkit
# ---------------------------------------------------------------------------

workspace = Workspace(
    root=tmp_dir,
    allowed=["read", "list", "search", "grep"],
)

# ---------------------------------------------------------------------------
# Expose the toolkit as MCP tools
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="toolkit-mcp-os",
    description="AgentOS exposing Workspace toolkit as MCP tools.",
    mcp_server=MCPServerConfig(
        tools=[workspace],
        enable_builtin_tools=False,
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Workspace: {tmp_dir}")
    agent_os.serve(app=app)
