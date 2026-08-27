"""
Expose a Toolkit as MCP tools
=============================

Pass a Toolkit directly to MCPServerConfig.tools — it auto-flattens into
individual MCP tools, same as Agent.parse_tools() does internally.

This example exposes Workspace's read-only tools (read_file, list_files,
search_content, grep_content) as MCP tools that any MCP client can call.

Prerequisites: none (no API key needed for file operations)
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/toolkit_tools.py
Try: connect an MCP client to http://localhost:7777/mcp and call read_file
"""

import tempfile
from pathlib import Path

from agno.os import AgentOS, MCPServerConfig
from agno.tools.workspace import Workspace

# ---------------------------------------------------------------------------
# Create a sample workspace with some files
# ---------------------------------------------------------------------------

tmp_dir = tempfile.mkdtemp(prefix="mcp_toolkit_")
sample_dir = Path(tmp_dir)

(sample_dir / "README.md").write_text("# Sample Project\n\nThis is a demo workspace.")
(sample_dir / "main.py").write_text("def hello():\n    return 'Hello, MCP!'\n")
(sample_dir / "utils.py").write_text(
    "# TODO: Add utility functions\ndef add(a, b):\n    return a + b\n"
)

print(f"Created sample workspace at: {tmp_dir}")

# ---------------------------------------------------------------------------
# Create Workspace toolkit with read-only tools
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
        tools=[workspace],  # Toolkit auto-flattens into individual tools
        enable_builtin_tools=False,
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nMCP tools available:")
    print("  - read_file(path, start_line, end_line, encoding)")
    print("  - list_files(directory, pattern, recursive, max_depth)")
    print("  - search_content(query, directory, limit)")
    print(
        "  - grep_content(pattern, directory, ignore_case, context_lines, files_only, limit)"
    )
    print("\nConnect an MCP client to http://localhost:7777/mcp")
    agent_os.serve(app=app)
