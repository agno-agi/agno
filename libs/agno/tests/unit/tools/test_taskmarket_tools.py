import asyncio
import io
import json
import signal
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from agno.tools.taskmarket import _CLI_OUTPUT_LIMIT_BYTES, TaskMarketTools


class FakePopen:
    def __init__(self, stdout: bytes = b'{"ok":true,"data":{"tasks":[]}}\n', stderr: bytes = b"", returncode: int = 0):
        self.stdout = self._pipe(stdout)
        self.stderr = self._pipe(stderr)
        self.returncode = returncode
        self.killed = False

    @staticmethod
    def _pipe(data: bytes):
        return io.BytesIO(data)

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


@pytest.fixture
def successful_run():
    with patch("agno.tools.taskmarket.subprocess.Popen") as run:
        run.return_value = FakePopen()
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def test_get_task_rejects_invalid_id_without_running_cli():
    with patch("agno.tools.taskmarket.subprocess.Popen") as run:
        result = json.loads(TaskMarketTools().get_task("not-a-task-id"))

    assert result == {"ok": False, "error": "task_id must be a 0x-prefixed 32-byte hex value"}
    run.assert_not_called()


def test_cli_failure_does_not_return_raw_stderr():
    with patch("agno.tools.taskmarket.subprocess.Popen") as run:
        run.return_value = FakePopen(returncode=1, stderr=b"wallet failed with secret material")
        result = json.loads(TaskMarketTools().list_tasks())

    assert result == {"ok": False, "error": "TaskMarket CLI command failed", "returncode": 1}
    assert "secret" not in json.dumps(result)


def test_successful_sync_command_is_not_killed(successful_run):
    result = json.loads(TaskMarketTools().list_tasks())

    assert result["ok"] is True
    assert successful_run.return_value.killed is False


def test_invalid_cli_json_returns_safe_error(successful_run):
    successful_run.return_value.stdout.close()
    successful_run.return_value.stdout = FakePopen._pipe(b"not-json")

    result = json.loads(TaskMarketTools().list_tasks())

    assert result == {"ok": False, "error": "TaskMarket CLI returned invalid JSON"}


def test_cli_timeout_returns_safe_error():
    process = FakePopen()
    wait_calls = 0

    def wait(timeout=None):
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            raise subprocess.TimeoutExpired("taskmarket", timeout)
        return process.returncode

    process.wait = wait
    with patch("agno.tools.taskmarket.subprocess.Popen", return_value=process):
        result = json.loads(TaskMarketTools(timeout=1).list_tasks())

    assert result == {"ok": False, "error": "TaskMarket CLI command timed out"}


def test_cli_oversized_sync_stdout_returns_safe_error():
    process = FakePopen(stdout=b"x" * (_CLI_OUTPUT_LIMIT_BYTES + 1))
    with patch("agno.tools.taskmarket.subprocess.Popen", return_value=process):
        result = json.loads(TaskMarketTools().list_tasks())

    assert result == {"ok": False, "error": "TaskMarket CLI output exceeded the safety byte limit"}
    assert process.killed is True


def test_cli_oversized_async_stdout_returns_safe_error():
    class FakeProcess:
        returncode = None

        def __init__(self):
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.killed = False
            self.waited = False
            self.stdout.feed_data(b"x" * (_CLI_OUTPUT_LIMIT_BYTES + 1))
            self.stdout.feed_eof()
            self.stderr.feed_eof()

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True
            return self.returncode

    async def run_test():
        process = FakeProcess()
        with patch("agno.tools.taskmarket.asyncio.create_subprocess_exec", return_value=process):
            result = json.loads(await TaskMarketTools()._arun(["task", "list"]))
        return process, result

    process, result = asyncio.run(run_test())

    assert result == {"ok": False, "error": "TaskMarket CLI output exceeded the safety byte limit"}
    assert process.killed is True
    assert process.waited is True


def test_process_group_signal_uses_group_id_after_parent_exits():
    class ExitedProcess:
        pid = 12345

    with (
        patch("agno.tools.taskmarket.os.killpg") as killpg,
        patch("agno.tools.taskmarket.os.getpgid", side_effect=ProcessLookupError) as getpgid,
    ):
        TaskMarketTools._signal_process_group(ExitedProcess(), signal.SIGKILL)

    killpg.assert_called_once_with(12345, signal.SIGKILL)
    getpgid.assert_not_called()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups are not available")
def test_async_cancellation_signals_group_after_parent_exits():
    class ExitedProcess:
        pid = 12345
        returncode = 0

        async def wait(self):
            return self.returncode

    with patch("agno.tools.taskmarket.os.killpg") as killpg:
        asyncio.run(TaskMarketTools()._cleanup_cancelled_process(ExitedProcess()))

    killpg.assert_called_once_with(12345, signal.SIGTERM)


def test_async_command_waits_for_exit_after_child_closes_output_fds():
    async def run_test():
        started = time.monotonic()
        result = await TaskMarketTools(cli_path=sys.executable, timeout=2)._arun(
            ["-c", "import os, time; os.close(1); os.close(2); time.sleep(0.25)"]
        )
        elapsed = time.monotonic() - started
        return result, elapsed

    result, elapsed = asyncio.run(run_test())

    assert json.loads(result) == {"ok": False, "error": "TaskMarket CLI returned invalid JSON"}
    assert elapsed >= 0.2


def test_async_command_timeout_covers_wait_after_output_closes():
    async def run_test():
        result = await TaskMarketTools(cli_path=sys.executable, timeout=0.1)._arun(
            ["-c", "import os, time; os.close(1); os.close(2); time.sleep(0.25)"]
        )
        return json.loads(result)

    assert asyncio.run(run_test()) == {"ok": False, "error": "TaskMarket CLI command timed out"}


def test_async_cancellation_repeated_during_subprocess_creation_cleans_up_late_process():
    creation_started = asyncio.Event()
    allow_creation_to_finish = asyncio.Event()

    class FakeProcess:
        returncode = None

        def __init__(self):
            self.terminated = False
            self.waited = False

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        async def wait(self):
            self.waited = True
            return self.returncode

    process = FakeProcess()
    tools = TaskMarketTools()

    async def create_process(*args, **kwargs):
        creation_started.set()
        await allow_creation_to_finish.wait()
        return process

    async def run_test():
        with patch("agno.tools.taskmarket.asyncio.create_subprocess_exec", new=create_process):
            task = asyncio.create_task(tools._arun([]))
            await creation_started.wait()
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            allow_creation_to_finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            for _ in range(10):
                if process.waited:
                    break
                await asyncio.sleep(0)

    asyncio.run(run_test())

    assert process.terminated is True
    assert process.waited is True


def test_create_is_only_registered_with_explicit_opt_in_and_spending_cap():
    tools = TaskMarketTools(allow_write=True, max_reward_usdc=5)

    assert "create_task" in tools.functions
    assert tools.functions["create_task"].requires_confirmation is True
    assert tools.async_functions["create_task"].requires_confirmation is True


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
    with patch("agno.tools.taskmarket.subprocess.Popen") as run:
        result = json.loads(
            TaskMarketTools(allow_write=True, max_reward_usdc="5").create_task(
                description="Implement a focused integration", reward_usdc="5.01", duration_hours=24
            )
        )

    assert result == {"ok": False, "error": "reward_usdc exceeds the configured 5 USDC spending cap"}
    run.assert_not_called()


@pytest.mark.parametrize(
    ("reward", "message"),
    [
        ("0.0000001", "reward_usdc must have at most 6 decimal places"),
        ("1e-1000000", "reward_usdc must have at most 6 decimal places"),
        ("1000000001", "reward_usdc is too large"),
    ],
)
def test_create_rejects_unrepresentable_usdc_before_formatting(reward, message):
    with patch("agno.tools.taskmarket.subprocess.Popen") as run:
        result = json.loads(
            TaskMarketTools(allow_write=True, max_reward_usdc="1000000000").create_task(
                description="Implement a focused integration", reward_usdc=reward, duration_hours=24
            )
        )

    assert result == {"ok": False, "error": message}
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def test_async_create_uses_safe_argument_vector():
    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b'{"ok":true,"data":{"taskId":"task-1"}}', b""

        async def wait(self):
            return self.returncode

    process = FakeProcess()
    with patch("agno.tools.taskmarket.asyncio.create_subprocess_exec", autospec=True) as create_process:
        create_process.return_value = process
        result = json.loads(
            asyncio.run(
                TaskMarketTools(allow_write=True, max_reward_usdc=5).acreate_task(
                    description="Create a task safely", reward_usdc="2.5", duration_hours=24, tags="python,agno"
                )
            )
        )

    assert result == {"ok": True, "data": {"taskId": "task-1"}}
    create_process.assert_awaited_once_with(
        "taskmarket",
        "task",
        "create",
        "--description",
        "Create a task safely",
        "--reward",
        "2.5",
        "--duration",
        "24",
        "--mode",
        "bounty",
        "--task-visibility",
        "public",
        "--submission-visibility",
        "public",
        "--tags",
        "python,agno",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=64 * 1024,
        start_new_session=True,
    )


def test_async_create_cancellation_terminates_and_waits_for_subprocess():
    communicate_started = asyncio.Event()
    allow_communicate_to_finish = asyncio.Event()

    class FakeProcess:
        returncode = None

        def __init__(self):
            self.terminated = False
            self.waited = False

        async def communicate(self):
            communicate_started.set()
            await allow_communicate_to_finish.wait()
            return b"", b""

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        async def wait(self):
            self.waited = True
            return self.returncode

    process = FakeProcess()

    async def run_and_cancel():
        with patch("agno.tools.taskmarket.asyncio.create_subprocess_exec", autospec=True, return_value=process):
            task = asyncio.create_task(
                TaskMarketTools(allow_write=True, max_reward_usdc=5).acreate_task(
                    description="Create a funded task", reward_usdc="2.5", duration_hours=24
                )
            )
            await communicate_started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run_and_cancel())

    assert process.terminated is True
    assert process.waited is True


def test_async_create_cancellation_during_subprocess_creation_blocks_retry():
    creation_started = asyncio.Event()
    allow_creation_to_finish = asyncio.Event()

    class FakeProcess:
        returncode = None

        def __init__(self):
            self.terminated = False
            self.waited = False

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        async def wait(self):
            self.waited = True
            return self.returncode

    process = FakeProcess()
    tools = TaskMarketTools(allow_write=True, max_reward_usdc=5)

    async def create_process(*args, **kwargs):
        creation_started.set()
        await allow_creation_to_finish.wait()
        return process

    async def run_and_cancel():
        with patch("agno.tools.taskmarket.asyncio.create_subprocess_exec", new=create_process):
            task = asyncio.create_task(
                tools.acreate_task(description="Create a funded task", reward_usdc="2.5", duration_hours=24)
            )
            await creation_started.wait()
            task.cancel()
            allow_creation_to_finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run_and_cancel())

    assert process.terminated is True
    assert process.waited is True
    assert tools._funded_create_outcome_unknown is True

    result = json.loads(tools.create_task(description="Retry the funded task", reward_usdc="2.5", duration_hours=24))
    assert result == {
        "ok": False,
        "error": "a previous funded task creation has an unknown outcome; inspect TaskMarket state before retrying",
        "retry_blocked": True,
        "outcome": "unknown",
    }


def test_concurrent_async_funded_creates_only_launch_one_cli_process():
    creation_started = asyncio.Event()
    allow_creation_to_finish = asyncio.Event()

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            creation_started.set()
            await allow_creation_to_finish.wait()
            return b'{"ok":true,"data":{"taskId":"task-1"}}', b""

        async def wait(self):
            return self.returncode

    tools = TaskMarketTools(allow_write=True, max_reward_usdc=5)

    async def run_test():
        with patch("agno.tools.taskmarket.asyncio.create_subprocess_exec", return_value=FakeProcess()) as run:
            first_task = asyncio.create_task(
                tools.acreate_task(description="Create the first task", reward_usdc="2.5", duration_hours=24)
            )
            await creation_started.wait()
            second_result = json.loads(
                await tools.acreate_task(description="Create the duplicate task", reward_usdc="2.5", duration_hours=24)
            )
            allow_creation_to_finish.set()
            first_result = json.loads(await first_task)
        return first_result, second_result, run

    first_result, second_result, run = asyncio.run(run_test())

    assert first_result == {"ok": True, "data": {"taskId": "task-1"}}
    assert second_result == {
        "ok": False,
        "error": "another funded task creation is already in progress; wait for it to finish before retrying",
        "retry_blocked": True,
        "outcome": "in_progress",
    }
    run.assert_awaited_once()


def test_cancelled_async_funded_create_blocks_sync_and_async_retries():
    tools = TaskMarketTools(allow_write=True, max_reward_usdc=5)
    tools._funded_create_outcome_unknown = True

    with patch("agno.tools.taskmarket.subprocess.Popen") as run:
        sync_result = json.loads(
            tools.create_task(description="Retry the funded task", reward_usdc="2.5", duration_hours=24)
        )
    async_result = json.loads(
        asyncio.run(tools.acreate_task(description="Retry the funded task", reward_usdc="2.5", duration_hours=24))
    )

    expected = {
        "ok": False,
        "error": "a previous funded task creation has an unknown outcome; inspect TaskMarket state before retrying",
        "retry_blocked": True,
        "outcome": "unknown",
    }
    assert sync_result == expected
    assert async_result == expected
    run.assert_not_called()


def test_failed_funded_create_blocks_retry_when_cli_outcome_cannot_be_reconciled_locally():
    process = FakePopen(returncode=1, stderr=b"upstream state unavailable")
    tools = TaskMarketTools(allow_write=True, max_reward_usdc=5)

    with patch("agno.tools.taskmarket.subprocess.Popen", return_value=process) as run:
        first_result = json.loads(
            tools.create_task(description="Create a funded task", reward_usdc="2.5", duration_hours=24)
        )
        retry_result = json.loads(
            tools.create_task(description="Retry the funded task", reward_usdc="2.5", duration_hours=24)
        )

    expected = {
        "ok": False,
        "error": "a previous funded task creation has an unknown outcome; inspect TaskMarket state before retrying",
        "retry_blocked": True,
        "outcome": "unknown",
    }
    assert first_result == expected
    assert retry_result == expected
    run.assert_called_once()


def test_failed_async_funded_create_blocks_retry_when_cli_outcome_cannot_be_reconciled_locally():
    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return b"", b"upstream state unavailable"

        async def wait(self):
            return self.returncode

    tools = TaskMarketTools(allow_write=True, max_reward_usdc=5)

    async def run_test():
        with patch("agno.tools.taskmarket.asyncio.create_subprocess_exec", return_value=FakeProcess()) as run:
            first_result = json.loads(
                await tools.acreate_task(description="Create a funded task", reward_usdc="2.5", duration_hours=24)
            )
            retry_result = json.loads(
                await tools.acreate_task(description="Retry the funded task", reward_usdc="2.5", duration_hours=24)
            )
        return first_result, retry_result, run

    first_result, retry_result, run = asyncio.run(run_test())

    expected = {
        "ok": False,
        "error": "a previous funded task creation has an unknown outcome; inspect TaskMarket state before retrying",
        "retry_blocked": True,
        "outcome": "unknown",
    }
    assert first_result == expected
    assert retry_result == expected
    run.assert_called_once()


def test_cancelled_create_cleanup_escalates_from_term_to_kill():
    class FakeProcess:
        returncode = None

        def __init__(self):
            self.terminate_calls = 0
            self.kill_calls = 0
            self.wait_calls = 0

        def terminate(self):
            self.terminate_calls += 1

        def kill(self):
            self.kill_calls += 1
            self.returncode = -9

        async def wait(self):
            self.wait_calls += 1
            return self.returncode

    process = FakeProcess()
    tools = TaskMarketTools(allow_write=True, max_reward_usdc=5)
    wait_results = iter([False, True])

    async def bounded_wait(_process):
        return next(wait_results)

    with patch.object(tools, "_wait_process_bounded", side_effect=bounded_wait) as wait_mock:
        asyncio.run(tools._terminate_and_wait(process))

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert wait_mock.await_count == 2


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"mode": "pitch"}, "unsupported task creation mode"),
        ({"task_visibility": "private"}, "private task creation is not supported"),
    ],
)
def test_create_rejects_flows_that_require_unexposed_security_options(kwargs, message):
    with patch("agno.tools.taskmarket.subprocess.Popen") as run:
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
