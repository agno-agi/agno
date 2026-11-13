"""Root `agno` app: branded home screen, version flag, command routing, and create-help defaults."""

import re

from typer.testing import CliRunner

from agnoctl import __version__
from agnoctl.main import app

runner = CliRunner()

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(value: str) -> str:
    return ANSI_ESCAPE.sub("", value)


def test_bare_invocation_shows_home_screen():
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    # The banner and every command group heading are present.
    assert "The CLI for AgentOS" in output
    for heading in ("Get started", "Operate", "Tokens"):
        assert heading in output
    assert "agno create" in output
    assert "agno create <name>" not in output  # the pre-interactive home screen advertised a required <name>
    assert __version__ in output


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in _strip_ansi(result.output)


def test_commands_are_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    for command in ("connect", "create", "status", "tokens", "up", "down", "restart"):
        assert command in output


def test_create_help_shows_interactive_defaults():
    result = runner.invoke(app, ["create", "--help"], env={"COLUMNS": "120"}, terminal_width=120)
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    output = " ".join(output.lower().replace("│", " ").split())
    assert "default: agent-platform." in output
    assert "when omitted: agentos-docker." in output
