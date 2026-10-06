"""Sprites command execution through Agno, without a live cloud account."""

import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("sprites")

from sprites import Sprite  # noqa: E402
from sprites.exceptions import NetworkError  # noqa: E402
from sprites.exec import CompletedProcess  # noqa: E402

from agno.tools.function import FunctionCall  # noqa: E402
from agno.tools.sprites import SpritesTools  # noqa: E402


@pytest.fixture
def sprite():
    instance = MagicMock(spec=Sprite)
    instance.client = MagicMock()
    instance.run.return_value = CompletedProcess(args=["pwd"], returncode=0, stdout=b"/home/sprite\n", stderr=b"")
    return instance


def test_registered_tool_runs_through_agno(sprite):
    tools = SpritesTools(sprite=sprite)
    assert set(tools.functions) == {"run_shell_command"}
    function = tools.functions["run_shell_command"]
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
    tools = SpritesTools(sprite=sprite, cwd="/home/sprite/project", env={"GREETING": "hello world"}, timeout=12)
    args = ["printf", "%s", "literal $(whoami); 'quoted' value"]

    tools.run_shell_command(args)

    sprite.run.assert_called_once_with(
        *args, capture_output=True, check=False, cwd="/home/sprite/project", env={"GREETING": "hello world"}, timeout=12
    )


def test_nonzero_exit_preserves_both_streams(sprite):
    sprite.run.return_value = CompletedProcess(
        args=["python", "broken.py"], returncode=7, stdout=b"partial result\n", stderr=b"failure\n"
    )

    result = json.loads(SpritesTools(sprite=sprite).run_shell_command(["python", "broken.py"]))

    assert result["exit_code"] == 7
    assert result["stdout"] == "partial result\n"
    assert result["stderr"] == "failure\n"


def test_timeout_is_unknown_exit_and_never_retried(sprite):
    sprite.run.side_effect = TimeoutError("command timed out")
    tools = SpritesTools(sprite=sprite, timeout=2)

    result = json.loads(tools.run_shell_command(["sleep", "30"]))
    tools.close()

    assert result["exit_code"] is None
    assert result["error"] == "timeout"
    assert "may still be running" in result["message"]
    sprite.run.assert_called_once()
    sprite.destroy.assert_not_called()
    sprite.client.close.assert_not_called()


def test_connection_loss_is_not_reported_as_command_failure_or_retried(sprite):
    sprite.run.side_effect = NetworkError("server detail containing a secret")

    result = json.loads(SpritesTools(sprite=sprite).run_shell_command(["apply-migration"]))

    assert result["exit_code"] is None
    assert result["error"] == "NetworkError"
    assert "unknown" in result["message"]
    assert "secret" not in json.dumps(result)
    sprite.run.assert_called_once()


def test_caller_owned_sprite_survives_cleanup_and_is_reused(sprite):
    tools = SpritesTools(sprite=sprite)
    tools.run_shell_command(["touch", "example.txt"])
    tools.close()
    tools.run_shell_command(["cat", "example.txt"])

    assert sprite.run.call_count == 2
    sprite.destroy.assert_not_called()
    sprite.client.close.assert_not_called()
    sprite.client.create_sprite.assert_not_called()


def test_output_is_bounded_and_invalid_utf8_does_not_break_result(sprite):
    sprite.run.return_value = CompletedProcess(args=["output"], returncode=0, stdout=b"abc\xffdef", stderr=b"123456")

    result = json.loads(SpritesTools(sprite=sprite, max_output_chars=4).run_shell_command(["output"]))

    assert result["stdout"] == "abc\ufffd"
    assert result["stderr"] == "1234"
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True


def test_empty_streams(sprite):
    sprite.run.return_value = CompletedProcess(args=["true"], returncode=0)
    result = json.loads(SpritesTools(sprite=sprite).run_shell_command(["true"]))
    assert result["stdout"] == result["stderr"] == ""


def test_command_can_be_disabled(sprite):
    assert not SpritesTools(sprite=sprite, enable_run_shell_command=False).functions


def test_confirmation_configuration_is_preserved(sprite):
    tools = SpritesTools(sprite=sprite, requires_confirmation_tools=["run_shell_command"])
    assert tools.functions["run_shell_command"].requires_confirmation is True


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
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
        SpritesTools(sprite=sprite).run_shell_command([])
    sprite.run.assert_not_called()
