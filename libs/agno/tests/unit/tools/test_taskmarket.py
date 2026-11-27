"""Unit tests for TaskMarketTools."""

import json
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.taskmarket import TaskMarketTools


@pytest.fixture
def tools():
    return TaskMarketTools(max_spend_usdc=10, network="base", cli_bin="taskmarket")


def test_init_registers_requester_tools(tools):
    names = [fn.name for fn in tools.functions.values()]
    for name in ("preview_task", "create_task", "get_task", "get_status", "list_submissions"):
        assert name in names
    assert "accept_submission" not in names


def test_accept_registered_when_enabled():
    names = [fn.name for fn in TaskMarketTools(enable_accept_reject=True).functions.values()]
    assert "accept_submission" in names
    assert "reject_submission" in names


def test_preview_does_not_pay(tools):
    with patch("subprocess.run") as run:
        raw = tools.preview_task("Write a parser", 5.0, 48, "one markdown file", tags="python")
    data = json.loads(raw)
    run.assert_not_called()
    assert data["ok"] is True
    assert data["paid"] is False
    assert data["requires_confirmation"] is True
    assert data["confirm_token"]
    preview = data["preview"]
    assert preview["reward_usdc"] == 5.0
    assert preview["reward_base_units"] == "5000000"
    assert preview["network"] == "base"
    assert preview["max_spend_usdc"] == 10.0
    assert preview["deliverables"] == "one markdown file"
    assert "Base" in preview["chain"]


def test_preview_rejects_over_cap(tools):
    data = json.loads(tools.preview_task("x", 11.0, 24, "file"))
    assert data["ok"] is False
    assert "max spend" in data["error"]


def test_preview_rejects_wrong_network():
    tools = TaskMarketTools(network="ethereum", max_spend_usdc=10)
    data = json.loads(tools.preview_task("x", 1.0, 24, "file"))
    assert data["ok"] is False
    assert "Base" in data["error"]


def test_create_requires_confirm(tools):
    with patch.object(tools, "_run_cli") as cli:
        data = json.loads(tools.create_task("x", 1.0, 24, "file", confirm=False))
    cli.assert_not_called()
    assert data["ok"] is False
    assert data["retry"] is False


def test_create_rejects_bad_token(tools):
    with patch.object(tools, "_run_cli") as cli:
        data = json.loads(tools.create_task("x", 1.0, 24, "file", confirm=True, confirm_token="nope"))
    cli.assert_not_called()
    assert data["ok"] is False


def test_preview_then_create_success_single_use(tools):
    preview = json.loads(tools.preview_task("Write a parser", 5.0, 48, "one markdown file", tags="python"))
    token = preview["confirm_token"]
    result = CompletedProcess(args=[], returncode=0, stdout="{\"success\":true,\"taskId\":\"0xabc\"}", stderr="")
    with patch.object(tools, "_run_cli", return_value=result) as cli:
        created = json.loads(tools.create_task("Write a parser", 5.0, 48, "one markdown file", confirm=True, confirm_token=token, tags="python"))
        second = json.loads(tools.create_task("Write a parser", 5.0, 48, "one markdown file", confirm=True, confirm_token=token, tags="python"))
    assert cli.call_count == 1
    assert created["ok"] is True
    assert created["task_id"] == "0xabc"
    assert "0xabc" in created["url"]
    assert created["paid"] is True
    assert second["ok"] is False


def test_create_mismatch_does_not_pay(tools):
    token = json.loads(tools.preview_task("Write a parser", 5.0, 48, "one markdown file"))["confirm_token"]
    with patch.object(tools, "_run_cli") as cli:
        data = json.loads(tools.create_task("Write a parser", 4.0, 48, "one markdown file", confirm=True, confirm_token=token))
    cli.assert_not_called()
    assert data["ok"] is False


def test_unknown_settlement_is_not_retried(tools):
    token = json.loads(tools.preview_task("Write a parser", 5.0, 48, "one markdown file"))["confirm_token"]
    result = CompletedProcess(args=[], returncode=1, stdout="", stderr="settlement status unknown")
    with patch.object(tools, "_run_cli", return_value=result) as cli:
        data = json.loads(tools.create_task("Write a parser", 5.0, 48, "one markdown file", confirm=True, confirm_token=token))
    assert cli.call_count == 1
    assert data["ok"] is False
    assert data["retry"] is False
    assert data["settlement"] == "unknown"


def test_get_task_and_status(tools):
    payload = {"id": "0xabc", "status": "open", "phase": "active", "reward": "5000000", "expiryTime": "2026-08-21T00:00:00Z", "submissionCount": 2, "submissionWindowOpen": True}
    with patch.object(tools, "_http_get", return_value=payload):
        task = json.loads(tools.get_task("0xabc"))
        status = json.loads(tools.get_status("0xabc"))
    assert task["ok"] is True
    assert status["status"] == "open"
    assert status["auto_accept"] is False
    assert status["review_required"] is True


def test_list_submissions_is_review_only(tools):
    with patch.object(tools, "_http_get", return_value=[{"id": "s1"}]):
        data = json.loads(tools.list_submissions("0xabc"))
    assert data["auto_accept"] is False
    assert data["auto_reject"] is False
    assert data["review"] == "human"


def test_accept_requires_confirm_and_flag(tools):
    data = json.loads(tools.accept_submission("0xabc", "0xworker", confirm=True))
    assert data["ok"] is False
    enabled = TaskMarketTools(enable_accept_reject=True)
    data = json.loads(enabled.accept_submission("0xabc", "0xworker", confirm=False))
    assert data["ok"] is False
    assert "confirm" in data["error"].lower() or "human" in data["error"].lower()

