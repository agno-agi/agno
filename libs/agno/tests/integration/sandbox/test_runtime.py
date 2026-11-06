"""Real runtime protocol acceptance without model calls. Requires a built runtime image."""

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio

from agno.sandbox.client import SandboxRuntimeClient
from agno.sandbox.docker import DockerSandbox

IMAGE = os.environ.get("AGNO_TEST_RUNTIME_IMAGE")
# The isolated network's range; a host with a 172.30.x network sets a free one.
SUBNET = {"subnet": os.environ["AGNO_TEST_SANDBOX_SUBNET"]} if os.environ.get("AGNO_TEST_SANDBOX_SUBNET") else {}
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not IMAGE, reason="Set AGNO_TEST_RUNTIME_IMAGE after building the cookbook image"),
]


@pytest_asyncio.fixture(params=["exec", "http"])
async def runtime_computer(request):
    """Every runtime case runs over both transports: the runtime spawned per request over
    docker exec, and the runtime served over HTTP from a port published on loopback."""
    options = {"network": "isolated", "runtime_port": 8765, **SUBNET} if request.param == "http" else {}
    provider = DockerSandbox(IMAGE, namespace="runtime-test-" + uuid4().hex, memory_mb=512, **options)
    handle = await provider.acreate("s", agent_id="a", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"})
    assert (handle.runtime_url is not None) == (request.param == "http")
    try:
        yield provider, handle, SandboxRuntimeClient(provider)
    finally:
        await provider.adestroy(handle)
        await provider.aremove_network()  # best effort: left in place while other sandboxes use it


async def test_reconnect_and_duplicate_dispatch_execute_only_once(runtime_computer):
    provider, computer, first = runtime_computer
    execution = await first.astart(
        computer, execution_id="e", run_id="r", sdk="fixture", input="hello", config={"delay": 0.3}
    )
    second = SandboxRuntimeClient(
        DockerSandbox(
            IMAGE,
            namespace=provider.namespace,
            memory_mb=512,
            network=provider.network,
            subnet=provider.subnet,
            runtime_port=provider.runtime_port,
        )
    )
    assert (
        await second.astart(computer, execution_id="e", run_id="r", sdk="fixture", input="hello", config={"delay": 0.3})
        == execution
    )
    pages = [page async for page in second.apages(execution, timeout=20)]
    assert pages[-1].result["type"] == "execution_finished"
    assert pages[-1].result["run"]["content"] == "hello"
    assert any(event["content"] == "hello" for page in pages for event in page.events)
    assert not any(event["event"] == "RunCompleted" for page in pages for event in page.events)
    replay = await first.apoll(execution, cursor=0)
    assert replay.events[0]["content"] == "hello"
    result = await provider.aexec(computer, ["cat", "fixture-effects.txt"])
    assert result.stdout == "r\n"


async def test_detached_polling_does_not_cancel_execution(runtime_computer):
    provider, computer, client = runtime_computer
    execution = await client.astart(
        computer, execution_id="e", run_id="r", sdk="fixture", input="late", config={"delay": 1}
    )
    with pytest.raises(TimeoutError, match="Detached"):
        await client.await_result(execution, timeout=0.01)
    result = await SandboxRuntimeClient(provider).await_result(execution, timeout=20)
    assert result["type"] == "execution_finished" and result["run"]["content"] == "late"
    assert (await provider.aget(computer.provider_ref)).state == "running"


async def test_runtime_cancel_stops_entire_computer(runtime_computer):
    provider, computer, client = runtime_computer
    execution = await client.astart(
        computer, execution_id="e", run_id="r", sdk="fixture", input="never", config={"delay": 30}
    )
    await client.acancel(execution)
    assert (await provider.aget(computer.provider_ref)).state == "exited"


async def test_runtime_rejects_overlapping_writer_without_repeating_first(runtime_computer):
    provider, computer, client = runtime_computer
    first = await client.astart(
        computer, execution_id="first", run_id="r", sdk="fixture", input="first", config={"delay": 2}
    )
    for _ in range(50):
        result = await provider.aexec(computer, ["test", "-f", "fixture-effects.txt"])
        if result.exit_code == 0:
            break
        await asyncio.sleep(0.01)
    second = await client.astart(computer, execution_id="second", run_id="r2", sdk="fixture", input="second")
    result = await client.await_result(second, timeout=20)
    assert result["type"] == "execution_error" and "already has a writer" in result["error"]
    assert (await client.await_result(first, timeout=20))["type"] == "execution_finished"
    assert (await provider.aexec(computer, ["cat", "fixture-effects.txt"])).stdout == "r\n"


async def test_binary_command_stdin_round_trip(runtime_computer):
    provider, computer, _ = runtime_computer
    payload = bytes(range(256)) * 4096
    result = await provider.aexec(
        computer,
        ["python", "-c", "import sys,hashlib; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())"],
        stdin=payload,
    )
    import hashlib

    assert result.stdout.strip() == hashlib.sha256(payload).hexdigest()


async def test_dead_worker_reports_unknown_without_reexecution(runtime_computer):
    provider, computer, client = runtime_computer
    execution = await client.astart(
        computer, execution_id="e", run_id="r", sdk="fixture", input="lost", config={"delay": 30}
    )
    script = "import pathlib,json,os,signal; p=next(pathlib.Path('/runtime/jobs').glob('*/status.json')); s=json.loads(p.read_text()); os.kill(s['pid'], signal.SIGKILL)"
    for _ in range(50):
        result = await provider.aexec(computer, ["python", "-c", script])
        if result.exit_code == 0:
            break
        await asyncio.sleep(0.02)
    else:
        pytest.fail("Runtime worker did not start")
    result = await client.await_result(execution, timeout=20)
    assert result["type"] == "execution_unknown"
    await client.astart(computer, execution_id="e", run_id="r", sdk="fixture", input="lost", config={"delay": 30})
    assert (await provider.aexec(computer, ["cat", "fixture-effects.txt"])).stdout == "r\n"


async def test_installed_sdk_adapters_construct_without_model_calls(runtime_computer):
    provider, computer, _ = runtime_computer
    script = """
from pathlib import Path
from agno.sandbox.runtime import _agent
root = Path('/runtime/native')
root.mkdir()
claude = _agent({'sdk': 'claude', 'agent_id': 'a'}, root)
codex = _agent({'sdk': 'codex', 'agent_id': 'a'}, root)
assert claude.sdk == 'claude-agent-sdk' and codex.sdk == 'codex'
assert claude.require_native_resume and codex.require_native_resume
assert claude.strict_persistence and codex.strict_persistence
assert claude.cwd == codex.cwd == '/workspace'
assert claude.retries == codex.retries == 0
assert claude.db.db_engine.dialect.name == 'sqlite'
claude.db.db_engine.dispose()
codex.db.db_engine.dispose()
print('SDK construction passed without model calls')
"""
    result = await provider.aexec(computer, ["python", "-c", script])
    assert result.exit_code == 0, result.stderr
    assert "SDK construction passed" in result.stdout


async def test_http_transport_long_polls_and_streams_events_as_they_land(runtime_computer):
    import time

    provider, computer, client = runtime_computer
    if computer.runtime_url is None:
        pytest.skip("exec transport")
    execution = await client.astart(
        computer, execution_id="lp", run_id="r", sdk="fixture", input="late", config={"delay": 1.0}
    )
    started = time.monotonic()
    first = await client.apoll(execution, wait=10)
    waited = time.monotonic() - started
    # The poll was held inside the container until the fixture journaled its event, well under the wait.
    assert [event.get("content") for event in first.events] == ["late"] or first.result is not None
    assert 0.5 < waited < 5
    result = await client.await_result(execution, timeout=20)
    assert result["run"]["content"] == "late"


async def test_http_transport_refuses_requests_without_the_containers_token(runtime_computer):
    import httpx

    provider, computer, client = runtime_computer
    if computer.runtime_url is None:
        pytest.skip("exec transport")
    assert computer.runtime_token
    async with httpx.AsyncClient() as raw:
        anonymous = await raw.get(computer.runtime_url + "/health")
        assert anonymous.status_code == 401
        owner = await raw.get(
            computer.runtime_url + "/health", headers={"Authorization": "Bearer " + computer.runtime_token}
        )
        assert owner.status_code == 200


_KILL_SERVER = (
    "import os, signal\n"
    "for pid in os.listdir('/proc'):\n"
    "    if not pid.isdigit() or int(pid) == os.getpid():\n"
    "        continue\n"
    "    try:\n"
    "        cmd = open(f'/proc/{pid}/cmdline', 'rb').read().replace(b'\\0', b' ')\n"
    "    except OSError:\n"
    "        continue\n"
    "    if b'agno.sandbox.runtime serve' in cmd:\n"
    "        os.kill(int(pid), signal.SIGKILL)\n"
    "        print(pid)\n"
)


async def test_the_turn_never_sees_the_control_token(runtime_computer):
    provider, computer, client = runtime_computer
    execution = await client.astart(computer, execution_id="env", run_id="r", sdk="fixture", input="x")
    await client.await_result(execution, timeout=20)
    seen = (await provider.aexec(computer, ["cat", "fixture-env.txt"])).stdout.split()
    assert "AGNO_SANDBOX_TEST_RUNTIME" in seen, "the fixture reports the variables it can see"
    assert "AGNO_SANDBOX_RUNTIME_TOKEN" not in seen, "the token never reaches the worker's environment"


async def test_server_crash_mid_turn_is_survived_by_the_turn_and_healed_by_the_supervisor(runtime_computer):
    import asyncio

    import httpx

    provider, computer, client = runtime_computer
    if computer.runtime_url is None:
        pytest.skip("exec transport")
    execution = await client.astart(
        computer, execution_id="crash", run_id="r", sdk="fixture", input="still here", config={"delay": 3.0}
    )
    killed = await provider.aexec(computer, ["python", "-c", _KILL_SERVER])
    assert killed.exit_code == 0 and killed.stdout.strip(), "the server process was found and killed"
    headers = {"Authorization": "Bearer " + computer.runtime_token}
    async with httpx.AsyncClient() as http:
        for _ in range(50):
            try:
                if (await http.get(computer.runtime_url + "/health", headers=headers, timeout=1)).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
        else:
            pytest.fail("the runtime server did not come back")
    result = await client.await_result(execution, timeout=20)
    assert result["type"] == "execution_finished" and result["run"]["content"] == "still here"
    assert (await provider.aexec(computer, ["cat", "fixture-effects.txt"])).stdout == "r\n", "ran exactly once"


_CONNECT = "import socket, sys; socket.create_connection((sys.argv[1], 8765), timeout=3); print('reached')"


@pytest.mark.parametrize("network", ["isolated", "bridge"])
async def test_sandboxes_cannot_reach_each_other_on_the_isolated_network(network):
    """Two sandboxes in one namespace: on the isolated bridge neither can open the other's runtime
    port, while on Docker's default bridge the same connection succeeds. The host still reaches
    both through their published loopback ports, which create already verified via /health."""
    provider = DockerSandbox(
        IMAGE, namespace="isolation-test-" + uuid4().hex, memory_mb=512, network=network, runtime_port=8765, **SUBNET
    )
    a = await provider.acreate("a", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"})
    b = await provider.acreate("b", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"})
    try:
        code, out, _ = await provider._docker(
            "container", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", b.provider_ref
        )
        ip = out.decode().strip()
        assert code == 0 and ip, "b has an address on the network"
        if network == "isolated":
            import ipaddress

            assert ipaddress.ip_address(ip) in ipaddress.ip_network(provider.subnet), (
                "addresses come from the pinned subnet"
            )
        result = await provider.aexec(a, ["python", "-c", _CONNECT, ip], timeout=10)
        if network == "isolated":
            assert result.exit_code != 0 and "reached" not in result.stdout, "a cannot open b's runtime port"
        else:
            assert result.exit_code == 0 and "reached" in result.stdout, "the default bridge lets a reach b"
    finally:
        await provider.adestroy(a)
        await provider.adestroy(b)
        await provider.aremove_network()  # best effort: left in place while other sandboxes use it


_SERVER_ENVIRON = (
    "import os\n"
    "for pid in os.listdir('/proc'):\n"
    "    if not pid.isdigit():\n"
    "        continue\n"
    "    try:\n"
    "        cmd = open(f'/proc/{pid}/cmdline', 'rb').read()\n"
    "        env = open(f'/proc/{pid}/environ', 'rb').read()\n"
    "    except OSError:\n"
    "        continue\n"
    "    if b'agno.sandbox.runtime' in cmd and b'serve' in cmd and b'supervise' not in cmd:\n"
    "        print('server', 'token' if b'AGNO_SANDBOX_RUNTIME_TOKEN=' in env else 'clean')\n"
)


async def test_host_exec_and_the_serving_process_do_not_carry_the_token(runtime_computer):
    """What stays: PID 1 and the supervisor keep the token in their exec-time environment, readable by
    the same UID. Only a separate UID for the runtime server removes that."""
    provider, computer, client = runtime_computer
    if computer.runtime_url is None:
        pytest.skip("exec transport")
    shell = await provider.aexec(computer, ["sh", "-c", 'echo "${AGNO_SANDBOX_RUNTIME_TOKEN:-absent}"'])
    assert shell.stdout.strip() == "absent", "a host-run command sees the variable blanked"
    server = await provider.aexec(computer, ["python", "-c", _SERVER_ENVIRON])
    assert server.stdout.strip() == "server clean", "the serving process has no token in its environ"
    execution = await client.astart(computer, execution_id="t", run_id="r", sdk="fixture", input="works")
    assert (await client.await_result(execution, timeout=20))["run"]["content"] == "works", "the token still works"


async def test_lost_poll_response_keeps_execution_available_for_another_client(runtime_computer, monkeypatch):
    import json

    provider, computer, first = runtime_computer
    if computer.runtime_url is not None:
        pytest.skip("Injects a lost reply on the exec transport")
    execution = await first.astart(
        computer, execution_id="e", run_id="r", sdk="fixture", input="survives", config={"delay": 1}
    )
    original = provider._docker
    lost = []

    async def lose_response(*args, **kwargs):
        response = await original(*args, **kwargs)
        if args[:2] == ("container", "exec") and kwargs.get("input_data"):
            command = json.loads(kwargs["input_data"])
            if command["argv"][-1] == "poll" and not lost:
                lost.append(True)
                raise TimeoutError("injected lost poll response")
        return response

    monkeypatch.setattr(provider, "_docker", lose_response)
    with pytest.raises(TimeoutError, match="lost poll"):
        await first.apoll(execution)
    assert (await provider.aget(computer.provider_ref)).state == "running"
    second = SandboxRuntimeClient(DockerSandbox(IMAGE, namespace=provider.namespace, memory_mb=512))
    assert (await second.await_result(execution, timeout=20))["run"]["content"] == "survives"
    assert (await provider.aexec(computer, ["cat", "fixture-effects.txt"])).stdout == "r\n"
