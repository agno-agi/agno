"""Sprites command execution through Agno, without a live cloud account."""

import json
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("sprites")

from sprites import Sprite  # noqa: E402
from sprites.exceptions import APIError, NetworkError  # noqa: E402
from sprites.exceptions import TimeoutError as SpriteTimeoutError  # noqa: E402
from sprites.exec import CompletedProcess  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.agent._tools import parse_tools  # noqa: E402
from agno.tools.function import FunctionCall  # noqa: E402
from agno.tools.shell import ShellTools  # noqa: E402
from agno.tools.sprites import SpritesTools  # noqa: E402


@pytest.fixture
def sprite():
    instance = MagicMock(spec=Sprite)
    instance.client = MagicMock()
    instance.run.return_value = CompletedProcess(args=["pwd"], returncode=0, stdout=b"/home/sprite\n", stderr=b"")
    return instance


def test_registered_tool_runs_through_agno(sprite):
    tools = SpritesTools(sprite=sprite)
    assert set(tools.functions) == {"run_sprite_command"}
    function = tools.functions["run_sprite_command"]
    function.process_entrypoint()
    call = FunctionCall(function=function, arguments={"args": ["pwd"]})

    execution = call.execute()

    assert execution.status == "success"
    assert json.loads(call.result) == {
        "stdout": "/home/sprite\n",
        "stderr": "",
        "exit_code": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
    }


def test_preserves_arguments_and_execution_options(sprite):
    tools = SpritesTools(sprite=sprite, cwd="/home/sprite/project", env={"GREETING": "hello world"}, timeout=12.5)
    args = ["printf", "%s", "literal $(whoami); 'quoted' value"]

    tools.run_sprite_command(args)

    sprite.run.assert_called_once_with(
        *args,
        capture_output=True,
        check=False,
        cwd="/home/sprite/project",
        env={"GREETING": "hello world"},
        timeout=12.5,
    )


def test_nonzero_exit_preserves_both_streams(sprite):
    sprite.run.return_value = CompletedProcess(
        args=["python", "broken.py"], returncode=7, stdout=b"partial result\n", stderr=b"failure\n"
    )

    result = json.loads(SpritesTools(sprite=sprite).run_sprite_command(["python", "broken.py"]))

    assert result["exit_code"] == 7
    assert result["stdout"] == "partial result\n"
    assert result["stderr"] == "failure\n"


@pytest.mark.parametrize("error_type", [SpriteTimeoutError, TimeoutError, FutureTimeoutError])
def test_timeout_is_unknown_exit_and_never_retried(sprite, error_type):
    sprite.run.side_effect = error_type("command timed out")
    tools = SpritesTools(sprite=sprite, timeout=2)

    result = json.loads(tools.run_sprite_command(["sleep", "30"]))
    tools.close()

    assert result["exit_code"] is None
    assert result["error"] == "timeout"
    assert "may still be running" in result["message"]
    sprite.run.assert_called_once()
    sprite.destroy.assert_not_called()
    sprite.client.close.assert_not_called()


def test_connection_loss_is_not_reported_as_command_failure_or_retried(sprite):
    sprite.run.side_effect = NetworkError("server detail containing a secret")

    result = json.loads(SpritesTools(sprite=sprite).run_sprite_command(["apply-migration"]))

    assert result["exit_code"] is None
    assert result["error"] == "NetworkError"
    assert "unknown" in result["message"]
    assert "secret" not in json.dumps(result)
    sprite.run.assert_called_once()


def test_caller_owned_sprite_survives_cleanup_and_is_reused(sprite):
    tools = SpritesTools(sprite=sprite)
    tools.run_sprite_command(["touch", "example.txt"])
    tools.close()
    tools.run_sprite_command(["cat", "example.txt"])

    assert sprite.run.call_count == 2
    sprite.destroy.assert_not_called()
    sprite.client.close.assert_not_called()
    sprite.client.create_sprite.assert_not_called()


def test_output_is_bounded_and_invalid_utf8_does_not_break_result(sprite):
    sprite.run.return_value = CompletedProcess(args=["output"], returncode=0, stdout=b"abc\xffdef", stderr=b"123456")

    result = json.loads(SpritesTools(sprite=sprite, max_output_chars=4).run_sprite_command(["output"]))

    assert result["stdout"] == "\ufffddef"
    assert result["stderr"] == "3456"
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True


def test_empty_streams(sprite):
    sprite.run.return_value = CompletedProcess(args=["true"], returncode=0)
    result = json.loads(SpritesTools(sprite=sprite).run_sprite_command(["true"]))
    assert result["stdout"] == result["stderr"] == ""


def test_command_can_be_disabled(sprite):
    tools = SpritesTools(sprite=sprite, enable_run_sprite_command=False)
    assert not tools.get_functions()
    assert not tools.get_async_functions()


def test_confirmation_configuration_is_preserved(sprite):
    tools = SpritesTools(sprite=sprite, requires_confirmation_tools=["run_sprite_command"])
    assert tools.functions["run_sprite_command"].requires_confirmation is True


@pytest.mark.parametrize("timeout", [None, "60", 0, -1, float("inf"), float("nan")])
def test_rejects_invalid_timeouts(sprite, timeout):
    with pytest.raises(ValueError, match="timeout"):
        SpritesTools(sprite=sprite, timeout=timeout)
    sprite.run.assert_not_called()


@pytest.mark.parametrize("limit", [0, -1])
def test_rejects_invalid_output_limits(sprite, limit):
    with pytest.raises(ValueError, match="max_output_chars"):
        SpritesTools(sprite=sprite, max_output_chars=limit)


def test_empty_command_does_not_execute(sprite):
    with pytest.raises(ValueError, match="args"):
        SpritesTools(sprite=sprite).run_sprite_command([])
    sprite.run.assert_not_called()


@pytest.mark.parametrize("sprite_first", [False, True])
def test_shell_tools_cannot_shadow_sprite_command(sprite, sprite_first):
    toolkits = [ShellTools(), SpritesTools(sprite=sprite)]
    if sprite_first:
        toolkits.reverse()
    agent = Agent(tools=toolkits)
    functions = {function.name: function for function in parse_tools(agent, toolkits, model=MagicMock())}
    assert set(functions) == {"run_shell_command", "run_sprite_command"}
    with patch("subprocess.run") as host_run:
        call = FunctionCall(function=functions["run_sprite_command"], arguments={"args": ["pwd"]})
        assert call.execute().status == "success"
        host_run.assert_not_called()
    sprite.run.assert_called_once()


@pytest.mark.parametrize("status_code", [401, 404, 429])
def test_api_error_logs_details_locally_and_returns_safe_status(sprite, status_code):
    sprite.run.side_effect = APIError("diagnostic detail", status_code=status_code, response="private response body")
    with patch("agno.tools.sprites.log_warning") as warning:
        result = json.loads(SpritesTools(sprite=sprite).run_sprite_command(["pwd"]))
    assert result["status_code"] == status_code
    assert result["error"] == "APIError"
    assert "diagnostic detail" in warning.call_args.args[0]
    assert str(status_code) in warning.call_args.args[0]
    assert "diagnostic detail" not in json.dumps(result)
    assert "private response body" not in json.dumps(result)
    sprite.run.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_hook", [False, True])
async def test_async_tool_keeps_sdk_off_event_loop_even_with_hook(sprite, with_hook):
    event_loop_thread = threading.get_ident()
    result = sprite.run.return_value

    def run(*args, **kwargs):
        assert threading.get_ident() != event_loop_thread
        return result

    async def hook(function_name, function, arguments):
        return await function(**arguments)

    sprite.run.side_effect = run
    tools = SpritesTools(sprite=sprite, requires_confirmation_tools=["run_sprite_command"])
    agent = Agent(tools=[tools], tool_hooks=[hook] if with_hook else None)
    functions = parse_tools(agent, [tools], model=MagicMock(), async_mode=True)
    assert len(functions) == 1
    assert functions[0].name == "run_sprite_command"
    assert functions[0].requires_confirmation is True
    call = FunctionCall(function=functions[0], arguments={"args": ["pwd"]})
    execution = await call.aexecute()
    assert execution.status == "success"
    assert json.loads(call.result)["stdout"] == "/home/sprite\n"
    sprite.run.assert_called_once()


def test_real_sdk_timeout_race_always_returns_timeout(monkeypatch):
    import asyncio

    from sprites import SpritesClient
    from sprites.loop import stop_loop

    async def hang(command):
        await asyncio.Event().wait()

    monkeypatch.setattr("sprites.websocket.run_ws_command", hang)
    client = SpritesClient(token="test-token")
    try:
        tools = SpritesTools(sprite=Sprite(name="test-sprite", client=client), timeout=0.01)
        for _ in range(30):
            result = json.loads(tools.run_sprite_command(["sleep", "30"]))
            assert result["error"] == "timeout"
            assert result["exit_code"] is None
    finally:
        client.close()
        stop_loop()
