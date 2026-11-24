"""Credential-free Docker acceptance. Set AGNO_TEST_DOCKER_IMAGE to opt in."""

import asyncio
import json
import os
from uuid import uuid4

import pytest
import pytest_asyncio

from agno.sandbox.base import SandboxError
from agno.sandbox.docker import DockerSandbox

IMAGE = os.environ.get("AGNO_TEST_DOCKER_IMAGE")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not IMAGE, reason="Set AGNO_TEST_DOCKER_IMAGE for real Docker tests"),
]


@pytest_asyncio.fixture
async def container():
    sandbox = DockerSandbox(IMAGE, namespace="test-" + uuid4().hex, memory_mb=256, workspace_mb=32)
    identity = {"session_id": "session", "agent_id": "coder", "env": {"EXPLICIT": "yes"}}
    handle = await sandbox.acreate(**identity)
    try:
        yield sandbox, identity, handle
    finally:
        await sandbox.adestroy(handle)


async def test_real_files_isolation_and_reuse(container, monkeypatch):
    sandbox, identity, handle = container
    monkeypatch.setenv("AGNO_DB_URL", "control-plane-secret")
    assert await sandbox.acreate(**identity) == handle
    result = await sandbox.aexec(
        handle, ["python", "-c", "from pathlib import Path; Path('hello').write_text('world')"]
    )
    assert result.exit_code == 0
    result = await sandbox.aexec(handle, ["cat", "hello"])
    assert result.stdout == "world"
    result = await sandbox.aexec(
        handle,
        [
            "python",
            "-c",
            "import os,json; print(json.dumps([os.getuid(),os.getenv('EXPLICIT'),os.getenv('AGNO_DB_URL'),os.getenv('HOME')]))",
        ],
    )
    assert json.loads(result.stdout) == [1000, "yes", None, "/runtime"]
    result = await sandbox.aexec(handle, ["sh", "-c", "touch /root-file; test -S /var/run/docker.sock"])
    assert result.exit_code != 0 and "Read-only file system" in result.stderr
    _, out, _ = await sandbox._docker("container", "inspect", handle.provider_ref)
    config = json.loads(out)[0]["HostConfig"]
    assert config["NetworkMode"] == "none"
    assert config["Init"] is True
    assert config["ReadonlyRootfs"] and not config["Privileged"] and not config["Binds"]
    assert config["CapDrop"] == ["ALL"] and config["Memory"] == 256 * 1024**2
    assert "no-new-privileges" in config["SecurityOpt"]
    result = await sandbox.aexec(handle, ["sh", "-c", "echo error >&2; exit 7"])
    assert result.exit_code == 7 and result.stderr == "error\n"


async def test_real_timeout_stops_container_and_prevents_reuse(container):
    sandbox, identity, handle = container
    result = await sandbox.aexec(handle, ["python", "-c", "import time; time.sleep(30)"], timeout=0.1)
    assert result.timed_out
    assert (await sandbox.aget(handle.provider_ref)).state == "exited"
    with pytest.raises(SandboxError, match="new generation"):
        await sandbox.acreate(**identity)


async def test_real_output_limit_stops_container(container):
    sandbox, _, handle = container
    result = await sandbox.aexec(handle, ["python", "-c", "print('x' * 1000000)"], max_output_bytes=100)
    assert result.output_limited and len(result.stdout) <= 100
    assert (await sandbox.aget(handle.provider_ref)).state == "exited"


async def test_real_cancel_stops_remote_children(container):
    sandbox, _, handle = container
    task = asyncio.create_task(sandbox.aexec(handle, ["sh", "-c", "touch started; sleep 30"], timeout=40))
    for _ in range(100):
        result = await sandbox.aexec(handle, ["test", "-f", "started"])
        if result.exit_code == 0:
            break
        await asyncio.sleep(0.02)
    else:
        pytest.fail("Remote process did not start")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await sandbox.aget(handle.provider_ref)).state == "exited"


async def test_real_concurrent_creation_and_idempotent_delete():
    namespace = "test-" + uuid4().hex
    first = DockerSandbox(IMAGE, namespace=namespace, memory_mb=256)
    second = DockerSandbox(IMAGE, namespace=namespace, memory_mb=256)
    handles = await asyncio.gather(
        first.acreate("concurrent", agent_id="coder"),
        second.acreate("concurrent", agent_id="coder"),
        return_exceptions=True,
    )
    try:
        assert not any(isinstance(handle, BaseException) for handle in handles), handles
        assert handles[0].provider_ref == handles[1].provider_ref
        await asyncio.gather(first.adestroy(handles[0]), second.adestroy(handles[1]))
        assert await first.aget(handles[0].provider_ref) is None
    finally:
        handle = await first.aget(first._name("concurrent", "coder", 1))
        if handle is not None:
            await first.adestroy(handle)


async def test_real_env_file_values_and_failed_start_cleanup():
    namespace = "test-" + uuid4().hex
    sandbox = DockerSandbox(IMAGE, namespace=namespace, memory_mb=256)
    value = " spaced = value # not a comment "
    handle = await sandbox.acreate("env", agent_id="coder", env={"EXPLICIT": value})
    try:
        result = await sandbox.aexec(handle, ["python", "-c", "import os; print(repr(os.environ['EXPLICIT']))"])
        assert result.stdout.strip() == repr(value)
    finally:
        await sandbox.adestroy(handle)
    broken = DockerSandbox(IMAGE, namespace=namespace, memory_mb=256, network="agno-missing-" + uuid4().hex)
    with pytest.raises(SandboxError, match="start failed"):
        await broken.acreate("broken", agent_id="coder")
    assert await broken.aget(broken._name("broken", "coder", 1)) is None


async def test_real_pause_keeps_files_and_resume_returns_the_same_container(container):
    sandbox, identity, handle = container
    assert (await sandbox.aexec(handle, ["sh", "-c", "echo kept > /workspace/warm"])).exit_code == 0
    await sandbox.apause(handle)
    assert (await sandbox.aget(handle.provider_ref)).state == "paused"
    with pytest.raises(SandboxError, match="paused; resume"):
        await sandbox.aexec(handle, ["cat", "/workspace/warm"])
    with pytest.raises(SandboxError, match="paused; resume it or destroy it"):
        await sandbox.acreate(**identity)
    resumed = await sandbox.aresume(handle)
    assert resumed.provider_ref == handle.provider_ref and resumed.state == "running"
    assert (await sandbox.aexec(resumed, ["cat", "/workspace/warm"])).stdout == "kept\n"
    # The cold path still works from paused: stop loses tmpfs and the generation cannot restart.
    await sandbox.apause(handle)
    await sandbox.astop(handle)
    assert (await sandbox.aget(handle.provider_ref)).state == "exited"
    with pytest.raises(SandboxError, match="recovery requires a new generation"):
        await sandbox.acreate(**identity)
