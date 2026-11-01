"""Tests for prepare_command() in agno.utils.mcp (agno#11420, item 1).

Regression coverage for the allowlist bypass: a previous version returned early
for any binary found on PATH (shutil.which), which made the ALLOWED_COMMANDS
check unreachable for PATH binaries such as `sh`, `bash` or `curl`.
"""

import pytest

from agno.utils.mcp import prepare_command


@pytest.mark.parametrize("command", ["npx -y @acme/server", "uvx some-server", "python server.py", "python3 -m server"])
def test_allowlisted_runtimes_pass_through(command):
    assert prepare_command(command) == command.split()


@pytest.mark.parametrize(
    "command",
    [
        "sh -c id",
        "bash -c id",
        "curl https://example.com",
        "cmd /c whoami",
    ],
)
def test_path_binaries_are_rejected_by_the_allowlist(command):
    """A bare executable name must be allowlisted, even when it is on PATH."""
    with pytest.raises(ValueError, match="one of the following executables"):
        prepare_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "npx foo; rm -rf /",
        "npx foo | cat",
        "npx foo & echo hi",
        "npx foo `id`",
        "npx foo $(id)",
        "npx foo\nid",
        "npx foo\rid",
    ],
)
def test_shell_metacharacters_are_rejected(command):
    with pytest.raises(ValueError, match="shell metacharacters"):
        prepare_command(command)


def test_empty_command_is_rejected():
    with pytest.raises(ValueError, match="can't be empty"):
        prepare_command("")


def test_binary_in_current_directory_still_allowed(tmp_path, monkeypatch):
    """The working-directory allowance is preserved: an explicit local binary
    is a deliberate local choice, not a PATH lookup."""
    server = tmp_path / "my-server"
    server.write_text("#!/bin/sh\necho hi\n")
    monkeypatch.chdir(tmp_path)
    assert prepare_command("my-server") == ["my-server"]
    assert prepare_command("./my-server") == ["./my-server"]
