"""Unit tests for TaskMarketTools."""

from datetime import datetime, timezone
import json
from subprocess import CompletedProcess
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agno.tools.taskmarket import TaskMarketTools


def _response(payload):
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_list_tasks_returns_public_task_data():
    """The toolkit exposes public TaskMarket tasks through the agent tool API."""
    tools = TaskMarketTools()
    payload = {
        "tasks": [
            {
                "id": "0xabc",
                "reward": "5000000",
                "status": "open",
                "submissionCount": 2,
            }
        ],
        "hasMore": False,
    }

    with patch("agno.tools.taskmarket.httpx.Client") as mock_client:
        client = mock_client.return_value.__enter__.return_value
        client.get.return_value = _response(payload)

        result = tools.list_tasks(status="open", limit=5)

    result_data = json.loads(result)
    assert result_data["tasks"][0]["id"] == "0xabc"
    assert result_data["tasks"][0]["status"] == "open"
    client.get.assert_called_once_with("/api/tasks", params={"status": "open", "limit": 5})


def test_preview_task_calculates_budget_and_keeps_request_unsubmitted():
    """The preview exposes Base/USDC cost information without a write call."""
    tools = TaskMarketTools()

    result = tools.preview_task(
        description="Collect and verify a short report",
        reward_usdc="0.50",
        duration_hours=24,
        tags="research, verification",
        max_spend_usdc="0.55",
    )

    result_data = json.loads(result)
    assert result_data["notSubmitted"] is True
    assert result_data["preview"]["estimatedMaxSpendUsdc"] == "0.538500"
    assert result_data["preview"]["maxSpendSufficient"] is True
    assert result_data["preview"]["confirmationToken"]
    assert result_data["preview"]["network"] == {"name": "Base", "chainId": 8453, "asset": "USDC"}
    assert result_data["preview"]["tags"] == ["research", "verification"]


def test_preview_task_rejects_modes_without_supported_create_arguments():
    """The toolkit must not advertise a mode its create command cannot express."""
    tools = TaskMarketTools()

    result = tools.preview_task(
        description="Collect and verify a short report",
        reward_usdc="0.50",
        duration_hours=24,
        tags="research,verification",
        max_spend_usdc="0.55",
        mode="auction",
    )

    result_data = json.loads(result)
    assert "auction" not in result_data["error"]
    assert result_data["notSubmitted"] is True


def test_preview_task_returns_structured_error_for_duration_overflow():
    """Extreme duration input must not escape as a timedelta overflow."""
    tools = TaskMarketTools()

    result = tools.preview_task(
        description="Collect and verify a short report",
        reward_usdc="0.50",
        duration_hours=1e300,
        tags="research,verification",
        max_spend_usdc="0.55",
    )

    result_data = json.loads(result)
    assert "duration_hours" in result_data["error"]
    assert result_data["notSubmitted"] is True


def test_create_task_requires_explicit_confirmation_before_calling_cli():
    """A preview-like create call must not invoke the payment-capable CLI."""
    tools = TaskMarketTools()

    with patch("agno.tools.taskmarket.subprocess.run") as run_cli:
        result = tools.create_task(
            description="Collect and verify a short report",
            reward_usdc="0.50",
            duration_hours=24,
            tags="research,verification",
            max_spend_usdc="0.55",
        )

    result_data = json.loads(result)
    assert result_data["confirmationRequired"] is True
    assert result_data["notSubmitted"] is True
    run_cli.assert_not_called()


def test_create_task_checks_base_wallet_then_calls_cli_once():
    """An authorized create verifies Base/USDC and returns the created ID."""
    tools = TaskMarketTools(cli_command="taskmarket")
    preview = json.loads(
        tools.preview_task(
            description="Collect and verify a short report",
            reward_usdc="0.50",
            duration_hours=24,
            tags="research,verification",
            max_spend_usdc="0.55",
        )
    )
    deposit = CompletedProcess(
        args=["taskmarket", "deposit"],
        returncode=0,
        stdout='{"ok":true,"data":{"network":"Base","chainId":8453,"currency":"USDC"}}',
        stderr="",
    )
    created = CompletedProcess(
        args=["taskmarket", "task", "create"],
        returncode=0,
        stdout='{"ok":true,"data":{"id":"0xcreated"}}',
        stderr="",
    )

    with patch("agno.tools.taskmarket.subprocess.run", side_effect=[deposit, created]) as run_cli:
        result = tools.create_task(
            description="Collect and verify a short report",
            reward_usdc="0.50",
            duration_hours=24,
            tags="research,verification",
            max_spend_usdc="0.55",
            confirm=True,
            confirmation_token=preview["preview"]["confirmationToken"],
        )

    result_data = json.loads(result)
    assert result_data["success"] is True
    assert result_data["taskId"] == "0xcreated"
    assert result_data["paymentState"] == "submitted_once"
    assert result_data["preview"]["deadlineUtc"] == preview["preview"]["deadlineUtc"]
    assert run_cli.call_count == 2
    assert run_cli.call_args_list[0].args[0] == ["taskmarket", "deposit"]
    create_args = run_cli.call_args_list[1].args[0]
    assert create_args[:3] == ["taskmarket", "task", "create"]
    assert "--confirm" not in create_args
    assert "--reward" in create_args


def test_create_task_does_not_recompute_approved_deadline():
    """Confirmation must use the deadline that the user actually approved."""
    tools = TaskMarketTools()
    fixed_now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    with patch("agno.tools.taskmarket.datetime") as datetime_type:
        datetime_type.now.return_value = fixed_now
        preview = json.loads(
            tools.preview_task(
                description="Collect and verify a short report",
                reward_usdc="0.50",
                duration_hours=24,
                tags="research,verification",
                max_spend_usdc="0.55",
            )
        )

        def unexpected_now_call(*args, **kwargs):
            raise AssertionError("confirmation recomputed the approved deadline")

        datetime_type.now.side_effect = unexpected_now_call
        deposit = CompletedProcess(
            args=["taskmarket", "deposit"],
            returncode=0,
            stdout='{"ok":true,"data":{"network":"Base","chainId":8453,"currency":"USDC"}}',
            stderr="",
        )
        created = CompletedProcess(
            args=["taskmarket", "task", "create"],
            returncode=0,
            stdout='{"ok":true,"data":{"id":"0xcreated"}}',
            stderr="",
        )
        with patch("agno.tools.taskmarket.subprocess.run", side_effect=[deposit, created]):
            result = tools.create_task(
                description="Collect and verify a short report",
                reward_usdc="0.50",
                duration_hours=24,
                tags="research,verification",
                max_spend_usdc="0.55",
                confirm=True,
                confirmation_token=preview["preview"]["confirmationToken"],
            )

    result_data = json.loads(result)
    assert result_data["preview"]["deadlineUtc"] == preview["preview"]["deadlineUtc"]


def test_create_task_does_not_retry_unknown_cli_failure():
    """A failed create never invites an automatic second payment attempt."""
    tools = TaskMarketTools()
    preview = json.loads(
        tools.preview_task(
            description="Collect and verify a short report",
            reward_usdc="0.50",
            duration_hours=24,
            tags="research,verification",
            max_spend_usdc="0.55",
        )
    )
    deposit = CompletedProcess(
        args=["taskmarket", "deposit"],
        returncode=0,
        stdout='{"ok":true,"data":{"network":"Base","chainId":8453,"currency":"USDC"}}',
        stderr="",
    )
    failed_create = CompletedProcess(
        args=["taskmarket", "task", "create"],
        returncode=1,
        stdout="",
        stderr="network timeout",
    )

    with patch("agno.tools.taskmarket.subprocess.run", side_effect=[deposit, failed_create]) as run_cli:
        result = tools.create_task(
            description="Collect and verify a short report",
            reward_usdc="0.50",
            duration_hours=24,
            tags="research,verification",
            max_spend_usdc="0.55",
            confirm=True,
            confirmation_token=preview["preview"]["confirmationToken"],
        )

    result_data = json.loads(result)
    assert result_data["paymentState"] == "unknown_or_not_settled"
    assert result_data["retry"] is False
    assert run_cli.call_count == 2


def test_create_task_requires_preview_token_after_confirmation():
    """Confirmation alone cannot authorize a create without an exact preview."""
    tools = TaskMarketTools()

    with patch("agno.tools.taskmarket.subprocess.run") as run_cli:
        result = tools.create_task(
            description="Collect and verify a short report",
            reward_usdc="0.50",
            duration_hours=24,
            tags="research,verification",
            max_spend_usdc="0.55",
            confirm=True,
        )

    result_data = json.loads(result)
    assert "confirmation_token" in result_data["error"]
    assert result_data["notSubmitted"] is True
    run_cli.assert_not_called()


@pytest.mark.asyncio
async def test_async_list_tasks_uses_the_same_public_contract():
    """Async agents can discover tasks through the same JSON interface."""
    tools = TaskMarketTools()
    response = _response({"tasks": [{"id": "0xasync", "status": "open"}]})

    with patch("agno.tools.taskmarket.httpx.AsyncClient") as mock_client:
        client = mock_client.return_value.__aenter__.return_value
        client.get = AsyncMock(return_value=response)

        result = await tools.alist_tasks(status="open", limit=1)

    assert json.loads(result)["tasks"][0]["id"] == "0xasync"
    client.get.assert_awaited_once_with("/api/tasks", params={"status": "open", "limit": 1})
