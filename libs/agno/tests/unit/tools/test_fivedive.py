"""Unit tests for FiveDiveTools class."""

import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.fivedive import FiveDiveTools


def _tool_names(tools: FiveDiveTools) -> list:
    return [tool.__name__ for tool in tools.tools]


@pytest.fixture
def fivedive_tools():
    return FiveDiveTools()


def _completed(returncode=0, stdout="", stderr=""):
    m = Mock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---- initialization ----

def test_all_flag_registers_every_tool():
    tools = FiveDiveTools(all=True)
    assert set(_tool_names(tools)) == {"deploy_agent", "fleet_status", "request_approval"}


def test_selective_registration():
    tools = FiveDiveTools(
        enable_deploy_agent=False, enable_request_approval=False, enable_fleet_status=True
    )
    assert _tool_names(tools) == ["fleet_status"]


# ---- CLI missing ----

def test_cli_not_installed_returns_clear_error(fivedive_tools):
    with patch("agno.tools.fivedive.shutil.which", return_value=None):
        out = fivedive_tools.fleet_status()
    assert "was not found on PATH" in out


# ---- fleet_status ----

def test_fleet_status_success(fivedive_tools):
    payload = '{"ok": true, "data": [{"name": "researcher", "state": "running"}]}'
    with patch("agno.tools.fivedive.shutil.which", return_value="/usr/local/bin/5dive"):
        with patch(
            "agno.tools.fivedive.subprocess.run", return_value=_completed(stdout=payload)
        ) as run:
            out = fivedive_tools.fleet_status()
    run.assert_called_once()
    assert run.call_args[0][0] == ["5dive", "agent", "list", "--json"]
    assert json.loads(out)["data"][0]["name"] == "researcher"


def test_fleet_status_nonzero_exit(fivedive_tools):
    with patch("agno.tools.fivedive.shutil.which", return_value="/usr/local/bin/5dive"):
        with patch(
            "agno.tools.fivedive.subprocess.run",
            return_value=_completed(returncode=1, stderr="not authenticated"),
        ):
            out = fivedive_tools.fleet_status()
    assert out.startswith("Error:")
    assert "not authenticated" in out


# ---- deploy_agent ----

def test_deploy_agent_creates_then_sends(fivedive_tools):
    with patch("agno.tools.fivedive.shutil.which", return_value="/usr/local/bin/5dive"):
        with patch(
            "agno.tools.fivedive.subprocess.run", return_value=_completed(stdout="ok")
        ) as run:
            out = fivedive_tools.deploy_agent(name="researcher", prompt="do the thing")
    assert run.call_count == 2
    create_cmd = run.call_args_list[0][0][0]
    send_cmd = run.call_args_list[1][0][0]
    assert create_cmd[:3] == ["5dive", "agent", "create"]
    assert send_cmd == ["5dive", "agent", "send", "researcher", "do the thing"]
    assert "researcher" in out


# ---- request_approval ----

def test_request_approval_two_step(fivedive_tools):
    add_out = _completed(stdout='{"ok": true, "data": {"display_id": "DIVE-42"}}')
    need_out = _completed(stdout='{"ok": true, "data": {"state": "blocked"}}')
    with patch("agno.tools.fivedive.shutil.which", return_value="/usr/local/bin/5dive"):
        with patch(
            "agno.tools.fivedive.subprocess.run", side_effect=[add_out, need_out]
        ) as run:
            out = fivedive_tools.request_approval(question="Ship it?", recommend="Approve")
    need_cmd = run.call_args_list[1][0][0]
    assert need_cmd[:4] == ["5dive", "task", "need", "DIVE-42"]
    assert "--type=approval" in need_cmd
    assert json.loads(out)["data"]["state"] == "blocked"
