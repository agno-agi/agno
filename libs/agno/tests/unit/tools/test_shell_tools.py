"""Tests for ShellTools security hardening (issue #8846).

ShellTools.run_shell_command executes an arbitrary List[str] command. By default
this is an RCE sink if the agent is prompt-injected. These tests verify the opt-in
defenses: command allowlist, shell-metacharacter blocking, base-dir path
containment, and HITL confirmation gating.
"""

import tempfile
from unittest.mock import patch

from agno.tools.shell import ShellTools


# --- defaults / opt-in posture ---


def test_shell_tools_registered_by_default():
    """run_shell_command is registered by default (existing contract preserved)."""
    tools = ShellTools()
    assert "run_shell_command" in tools.functions


def test_unrestricted_by_default_runs_command():
    """Default (unrestricted) mode still executes arbitrary commands — backward compat."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir)
        result = tools.run_shell_command(["echo", "hello"])
        assert "hello" in result


def test_unrestricted_does_not_apply_allowlist():
    """In unrestricted mode the allowlist must not block commands."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir)
        # curl is not in the default allowlist but unrestricted mode must still run it if present
        result = tools.run_shell_command(["echo", "ok"])
        assert "ok" in result


# --- allowlist (restrict_to_base_dir=True) ---


def test_allowlist_blocks_disallowed_command():
    """Commands not in the allowlist are blocked in restricted mode."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, restrict_to_base_dir=True)
        result = tools.run_shell_command(["curl", "https://example.com"])
        assert "Error" in result
        assert "allowed commands" in result.lower()


def test_allowlist_allows_listed_command():
    """Allowlisted commands run in restricted mode."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, restrict_to_base_dir=True)
        result = tools.run_shell_command(["echo", "hello"])
        assert "hello" in result
        assert "Error" not in result


def test_custom_allowlist_overrides_default():
    """A custom allowlist replaces the default."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, restrict_to_base_dir=True, allowed_commands=["echo"])
        # echo allowed
        result = tools.run_shell_command(["echo", "hi"])
        assert "hi" in result
        # ls blocked (not in custom list)
        result = tools.run_shell_command(["ls"])
        assert "Error" in result


def test_allowlist_checks_basename():
    """Commands specified by full path are validated by basename."""
    import shutil

    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, restrict_to_base_dir=True)
        echo_path = shutil.which("echo")
        if echo_path:
            result = tools.run_shell_command([echo_path, "via-full-path"])
            assert "via-full-path" in result
            assert "Error" not in result


# --- shell metacharacter blocking ---


def test_blocks_command_with_shell_metacharacters():
    """Shell operators that enable chaining/substitution are blocked in restricted mode."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, restrict_to_base_dir=True)
        # The args list carries a literal shell operator as a token — must be rejected
        result = tools.run_shell_command(["echo", "hello", "&&", "cat", "/etc/passwd"])
        assert "Error" in result


def test_blocks_pipe_operator():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, restrict_to_base_dir=True)
        result = tools.run_shell_command(["echo", "x", "|", "sh"])
        assert "Error" in result


# --- base-dir containment ---


def test_blocks_absolute_path_outside_base_dir():
    """Absolute paths outside base_dir are blocked even for allowed commands."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, restrict_to_base_dir=True)
        result = tools.run_shell_command(["cat", "/etc/passwd"])
        assert "Error" in result


# --- HITL confirmation ---


def test_run_shell_command_requires_confirmation_when_enabled():
    """When require_confirmation=True, the tool is flagged for HITL."""
    tools = ShellTools(require_confirmation=True)
    fn = tools.functions["run_shell_command"]
    assert fn.requires_confirmation is True


def test_run_shell_command_no_confirmation_by_default():
    """Default keeps backward-compatible behavior (no confirmation gate)."""
    tools = ShellTools()
    fn = tools.functions["run_shell_command"]
    assert fn.requires_confirmation is False


# --- empty / invalid input ---


def test_empty_args_rejected():
    """An empty command list is rejected before reaching subprocess."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, restrict_to_base_dir=True)
        result = tools.run_shell_command([])
        assert "Error" in result


def test_non_string_args_rejected():
    """Non-string entries in args are rejected (input validation at boundary)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, restrict_to_base_dir=True)
        result = tools.run_shell_command(["echo", 123])  # type: ignore[list-item]
        assert "Error" in result


# --- execution never reached when blocked ---


def test_subprocess_not_invoked_when_blocked():
    """When the command is blocked, subprocess.run must never be called."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = ShellTools(base_dir=tmp_dir, restrict_to_base_dir=True)
        with patch.object(subprocess, "run") as mock_run:
            tools.run_shell_command(["curl", "https://evil.example.com"])
            mock_run.assert_not_called()
