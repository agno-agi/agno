"""Vercel exact-session contract using actual SDK handles without network."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("vercel.sandbox")

import httpx2
from vercel.sandbox import NetworkPolicy, Sandbox, SandboxApiError, SandboxResources, SandboxStatus
from vercel.sandbox._internal.state import SandboxRuntimeSessionState, SandboxState

from agno.sandbox.base import SandboxError, SandboxSpec
from agno.sandbox.vercel import VercelSandboxProvider
from tests.unit.sandbox.test_hosted import Journal


def provider():
    return VercelSandboxProvider("tests", Journal(), token="test-token", team_id="team", project_id="project")


def sandbox(*, session_id="session", status=SandboxStatus.RUNNING, service=None):
    return Sandbox(
        payload=SandboxState(
            name="computer",
            project_id="project",
            current_session_id=session_id,
            status=status,
            tags={"namespace": "vercel:tests", "token": "intent"},
            current_session=SandboxRuntimeSessionState(
                id=session_id, sandbox_name="computer", project_id="project", status=status
            ),
        ),
        service=service or SimpleNamespace(),
    )


def client_for(value, compute):
    client = SimpleNamespace(get_sandbox=AsyncMock(return_value=compute))

    @asynccontextmanager
    async def context():
        yield client

    value._client = context
    return client


@pytest.mark.asyncio
async def test_exact_session_command_never_recovers_or_replays():
    value = provider()
    error = SandboxApiError(httpx2.Response(410), "stopped", data={"code": "sandbox_stopped"})
    service = SimpleNamespace(run_process=AsyncMock(side_effect=error), get_sandbox=AsyncMock())
    compute = sandbox(service=service)
    client_for(value, compute)
    with pytest.raises(SandboxApiError):
        await value._command(value._computer(compute).provider_ref, ["python", "-V"], timeout=5)
    assert service.run_process.await_count == 1
    assert service.run_process.call_args.kwargs["session_id"] == "session"
    assert service.run_process.call_args.kwargs["sudo"] is True
    service.get_sandbox.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_session_and_stopped_session_fail_before_execution():
    value = provider()
    first = sandbox()
    reference = value._computer(first).provider_ref
    client_for(value, sandbox(session_id="replacement"))
    with pytest.raises(SandboxError, match="session changed"):
        await value._command(reference, ["true"], timeout=5)
    client_for(value, sandbox(status=SandboxStatus.STOPPED))
    with pytest.raises(SandboxError, match="implicit resume"):
        await value._command(reference, ["true"], timeout=5)


@pytest.mark.asyncio
async def test_create_is_ephemeral_scoped_and_uses_sdk_resource_models():
    value = provider()
    client = client_for(value, sandbox())
    client.create_sandbox = AsyncMock(return_value=sandbox())
    spec = SandboxSpec("a", "s", 1, "prepared:v1", memory_mb=4096, pids_limit=None, workspace_mb=None)
    await value._create(spec, {"name": "logical", "token": "a" * 32})
    kwargs = client.create_sandbox.call_args.kwargs
    assert kwargs["persistent"] is False and kwargs["destroy"] is False
    assert kwargs["name"] == "logical-" + "a" * 12
    assert isinstance(kwargs["resources"], SandboxResources)
    assert kwargs["resources"].to_api_dict() == {"vcpus": 2, "memory": 4096}
    assert isinstance(kwargs["network_policy"], NetworkPolicy)
    assert kwargs["network_policy"].mode == "deny-all"
    assert kwargs["env"] == {}


@pytest.mark.asyncio
async def test_client_pool_is_closed_after_each_operation(monkeypatch):
    value = provider()
    client = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(value._sdk.SandboxClient, "create", lambda **kwargs: client)
    with pytest.raises(RuntimeError):
        async with value._client():
            raise RuntimeError("operation failed")
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_wrong_project_is_rejected_before_lookup():
    value = provider()
    client = client_for(value, sandbox())
    with pytest.raises(SandboxError, match="different project"):
        await value._lookup(client, '["other","computer","session"]')
    client.get_sandbox.assert_not_awaited()
