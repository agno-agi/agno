import json
from subprocess import CompletedProcess

import pytest

from agno.sandbox.docker import DockerSandboxProvider


@pytest.mark.asyncio
async def test_daemon_failure_is_not_container_death(monkeypatch):
    provider = DockerSandboxProvider()

    async def unavailable(*args, **kwargs):
        return CompletedProcess([], 1, "", "Cannot connect to the Docker daemon")

    monkeypatch.setattr(provider, "_command", unavailable)
    with pytest.raises(RuntimeError, match="inspect"):
        await provider.aget("agno-sandbox-test-1")

    async def missing(*args, **kwargs):
        return CompletedProcess([], 1, "", "Error: No such container: agno-sandbox-test-1")

    monkeypatch.setattr(provider, "_command", missing)
    assert await provider.aget("agno-sandbox-test-1") is None


@pytest.mark.asyncio
async def test_refuses_unmanaged_containers_and_reports_oom(monkeypatch):
    provider = DockerSandboxProvider()
    data = {"Config": {"Labels": {}}, "State": {"Running": False, "ExitCode": 137, "OOMKilled": True}}

    async def inspect(*args, **kwargs):
        return CompletedProcess([], 0, json.dumps([data]), "")

    monkeypatch.setattr(provider, "_command", inspect)
    with pytest.raises(ValueError, match="not managed"):
        await provider.aget("agno-sandbox-test-1")
    data["Config"]["Labels"]["agno.sandbox"] = "true"
    handle = await provider.aget("agno-sandbox-test-1")
    assert handle.status == "stopped" and "OOM=True" in handle.reason and "137" in handle.reason
    with pytest.raises(ValueError, match="Invalid"):
        await provider.aget("unrelated-container")
