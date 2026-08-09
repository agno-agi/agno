import asyncio
import json
import subprocess
from unittest.mock import patch

import pytest

from agno.tools.taskmarket import TaskMarketTools


@pytest.fixture
def successful_run():
    with patch("agno.tools.taskmarket.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"ok":true,"data":{"tasks":[]}}\n', stderr=""
        )
        yield run


def test_read_tools_are_registered_by_default():
    tools = TaskMarketTools()

    assert set(tools.functions) == {"list_tasks", "get_task"}


def test_list_tasks_uses_argument_vector_and_validated_filters(successful_run):
    tools = TaskMarketTools(cli_path="/usr/local/bin/taskmarket", timeout=12)

    result = json.loads(
        tools.list_tasks(
            status="open",
            mode="bounty",
            tags="python,agno",
            reward_min=1.5,
            reward_max=10,
            deadline_hours=24,
            limit=5,
            cursor="next-page",
        )
    )

    assert result["ok"] is True
    successful_run.assert_called_once_with(
        [
            "/usr/local/bin/taskmarket",
            "task",
            "list",
            "--status",
            "open",
            "--mode",
            "bounty",
            "--tags",
            "python,agno",
            "--reward-min",
            "1.5",
            "--reward-max",
            "10",
            "--deadline-hours",
            "24",
            "--limit",
            "5",
            "--cursor",
            "next-page",
        ],
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )


def test_get_task_rejects_invalid_id_without_running_cli():
    with patch("agno.tools.taskmarket.subprocess.run") as run:
        result = json.loads(TaskMarketTools().get_task("not-a-task-id"))

    assert result == {"ok": False, "error": "task_id must be a 0x-prefixed 32-byte hex value"}
    run.assert_not_called()


def test_cli_failure_does_not_return_raw_stderr():
    with patch("agno.tools.taskmarket.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="wallet failed with secret material"
        )
        result = json.loads(TaskMarketTools().list_tasks())

    assert result == {"ok": False, "error": "TaskMarket CLI command failed", "returncode": 1}
    assert "secret" not in json.dumps(result)


def test_invalid_cli_json_returns_safe_error(successful_run):
    successful_run.return_value.stdout = "not-json"

    result = json.loads(TaskMarketTools().list_tasks())

    assert result == {"ok": False, "error": "TaskMarket CLI returned invalid JSON"}


def test_cli_timeout_returns_safe_error():
    with patch("agno.tools.taskmarket.subprocess.run", side_effect=subprocess.TimeoutExpired("taskmarket", 7)):
        result = json.loads(TaskMarketTools(timeout=7).list_tasks())

    assert result == {"ok": False, "error": "TaskMarket CLI command timed out"}


def test_create_is_only_registered_with_explicit_opt_in_and_spending_cap():
    tools = TaskMarketTools(allow_write=True, max_reward_usdc=5)

    assert "create_task" in tools.functions
    assert tools.functions["create_task"].requires_confirmation is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"allow_write": True}, "max_reward_usdc is required"),
        ({"max_reward_usdc": 5}, "max_reward_usdc requires allow_write=True"),
        ({"allow_write": True, "max_reward_usdc": 0}, "max_reward_usdc must be greater than zero"),
    ],
)
def test_write_configuration_requires_opt_in_and_positive_cap(kwargs, message):
    with pytest.raises(ValueError, match=message):
        TaskMarketTools(**kwargs)


def test_create_enforces_cap_before_cli_execution():
    with patch("agno.tools.taskmarket.subprocess.run") as run:
        result = json.loads(
            TaskMarketTools(allow_write=True, max_reward_usdc="5").create_task(
                description="Implement a focused integration", reward_usdc="5.01", duration_hours=24
            )
        )

    assert result == {"ok": False, "error": "reward_usdc exceeds the configured 5 USDC spending cap"}
    run.assert_not_called()


def test_create_uses_fixed_cli_options(successful_run):
    tools = TaskMarketTools(allow_write=True, max_reward_usdc=5)

    tools.create_task(
        description="Implement a focused integration",
        reward_usdc="2.5",
        duration_hours=24,
        mode="claim",
        tags="python,agno",
        task_visibility="unlisted",
        submission_visibility="winner_only",
    )

    successful_run.assert_called_once_with(
        [
            "taskmarket",
            "task",
            "create",
            "--description",
            "Implement a focused integration",
            "--reward",
            "2.5",
            "--duration",
            "24",
            "--mode",
            "claim",
            "--task-visibility",
            "unlisted",
            "--submission-visibility",
            "winner_only",
            "--tags",
            "python,agno",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mode": "pitch"}, "unsupported task creation mode"),
        ({"task_visibility": "private"}, "private task creation is not supported"),
    ],
)
def test_create_rejects_flows_that_require_unexposed_security_options(kwargs, message):
    with patch("agno.tools.taskmarket.subprocess.run") as run:
        result = json.loads(
            TaskMarketTools(allow_write=True, max_reward_usdc=5).create_task(
                description="Implement a focused integration", reward_usdc="2.5", duration_hours=24, **kwargs
            )
        )

    assert result == {"ok": False, "error": message}
    run.assert_not_called()


def test_async_variants_are_registered_and_do_not_block(successful_run):
    tools = TaskMarketTools()

    result = json.loads(asyncio.run(tools.alist_tasks(limit=2)))

    assert result["ok"] is True
    assert set(tools.async_functions) == {"list_tasks", "get_task"}


def test_registered_async_read_functions_have_usable_parameter_schemas():
    tools = TaskMarketTools()

    list_tasks = tools.async_functions["list_tasks"]
    get_task = tools.async_functions["get_task"]
    list_tasks.process_entrypoint()
    get_task.process_entrypoint()

    assert set(list_tasks.parameters["properties"]) == {
        "status",
        "mode",
        "tags",
        "reward_min",
        "reward_max",
        "deadline_hours",
        "limit",
        "cursor",
    }
    assert list_tasks.parameters["required"] == []
    assert set(get_task.parameters["properties"]) == {"task_id"}
    assert get_task.parameters["required"] == ["task_id"]


def test_registered_async_write_function_has_usable_parameter_schema():
    tools = TaskMarketTools(allow_write=True, max_reward_usdc=5)
    create_task = tools.async_functions["create_task"]
    create_task.process_entrypoint()

    assert set(create_task.parameters["properties"]) == {
        "description",
        "reward_usdc",
        "duration_hours",
        "mode",
        "tags",
        "task_visibility",
        "submission_visibility",
    }
    assert create_task.parameters["required"] == ["description", "reward_usdc", "duration_hours"]
