"""Importing agents and skills must not require the optional `mcp` extra."""

import subprocess
import sys

_BLOCK_MCP = """
import sys
sys.modules["mcp"] = None
sys.modules["fastmcp"] = None
"""


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", _BLOCK_MCP + code], capture_output=True, text=True, timeout=120)


def test_agent_team_and_skills_import_without_mcp() -> None:
    result = _run(
        "from agno.agent import Agent\nfrom agno.team import Team\nfrom agno.skills import MCPSkills, Skills\n"
    )
    assert result.returncode == 0, result.stderr


def test_mcp_skills_reports_missing_mcp_when_constructed() -> None:
    result = _run("from agno.skills import MCPSkills\nMCPSkills(command='python server.py')\n")
    assert result.returncode != 0
    assert "mcp" in result.stderr and "not installed" in result.stderr
