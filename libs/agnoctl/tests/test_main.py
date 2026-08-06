"""Root `agno` app: branded home screen, version flag, command routing, and create-help defaults."""

import re

from typer.testing import CliRunner

from agnoctl import __version__
from agnoctl.main import app

runner = CliRunner()


def test_bare_invocation_shows_home_screen():
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    # The banner and every command group heading are present.
    assert "The CLI for AgentOS" in result.output
    for heading in ("Get started", "Operate", "Tokens"):
        assert heading in result.output
    assert "agno create" in result.output
    assert "agno create <name>" not in result.output  # the pre-interactive home screen advertised a required <name>
    assert __version__ in result.output


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_commands_are_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("connect", "create", "status", "tokens", "up", "down", "restart"):
        assert command in result.output


def test_create_help_shows_interactive_defaults():
    result = runner.invoke(app, ["create", "--help"])
    assert result.exit_code == 0
    output = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    output = " ".join(output.lower().replace("│", " ").split())
    assert "default: agentos." in output
    assert "when omitted: agentos-docker." in output
