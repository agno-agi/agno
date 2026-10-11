"""Installed-SDK contract checks; network endpoints are replaced explicitly."""

import datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("e2b")

from e2b.api.client.models import SandboxDetail, SandboxState

from agno.sandbox.base import SandboxError, SandboxSpec
from agno.sandbox.e2b import E2BSandboxProvider
from tests.unit.sandbox.test_hosted import Journal


def provider():
    return E2BSandboxProvider("tests", Journal(), api_key="e2b_test-key")


def detail(**kwargs):
    values = dict(
        template_id="template",
        sandbox_id="computer",
        client_id="client",
        started_at=datetime.datetime.now(datetime.timezone.utc),
        end_at=datetime.datetime.now(datetime.timezone.utc),
        envd_version="0.5.6",
        cpu_count=2,
        memory_mb=2048,
        disk_size_mb=1024,
        state=SandboxState.RUNNING,
        envd_access_token="transport-only",
        metadata={},
        allow_internet_access=False,
    )
    values.update(kwargs)
    return SandboxDetail(**values)


def test_read_only_detail_and_transport_never_connect(monkeypatch):
    from e2b.api.client.api.sandboxes import get_sandboxes_sandbox_id

    calls = []
    monkeypatch.setattr(
        get_sandboxes_sandbox_id,
        "sync_detailed",
        lambda ref, **kwargs: calls.append(ref) or SimpleNamespace(status_code=200, parsed=detail()),
    )
    value = provider()
    monkeypatch.setattr(value._sdk.Sandbox, "connect", lambda *a, **k: pytest.fail("connect can resume compute"))
    sandbox = value._transport("computer")
    assert sandbox.sandbox_id == "computer"
    assert sandbox.connection_config.retries == 0
    assert calls == ["computer"]


def test_paused_transport_is_rejected_without_resuming(monkeypatch):
    value = provider()
    monkeypatch.setattr(value, "_detail", lambda ref: detail(state=SandboxState.PAUSED))
    with pytest.raises(SandboxError, match="implicit resume"):
        value._transport("computer")


@pytest.mark.asyncio
async def test_create_config_disables_retry_resume_and_inherited_credentials(monkeypatch):
    value = provider()
    calls = []
    monkeypatch.setenv("AGNO_DB_URL", "not-forwarded")
    monkeypatch.setattr(
        value._sdk.Sandbox, "create", lambda **kwargs: calls.append(kwargs) or SimpleNamespace(sandbox_id="computer")
    )
    spec = SandboxSpec("a", "s", 1, "template", pids_limit=None, workspace_mb=None, env={"MODEL_KEY": "explicit"})
    result = await value._create(spec, {"token": "intent"})
    assert result.provider_ref == "computer"
    assert calls[0]["retries"] == 0 and calls[0]["secure"] is True
    assert calls[0]["lifecycle"] == {"on_timeout": "kill", "auto_resume": False}
    assert calls[0]["envs"] == {"MODEL_KEY": "explicit"}
    assert calls[0]["allow_internet_access"] is False


@pytest.mark.asyncio
async def test_inventory_uses_sdk_query_and_visits_all_pages(monkeypatch):
    from e2b.api.client.api.sandboxes import get_v2_sandboxes
    from e2b.sandbox.sandbox_api import SandboxQuery

    value = provider()
    calls = []

    class Pages:
        has_next = True
        index = 0

        def next_items(self):
            self.index += 1
            self.has_next = self.index < 2
            return [
                SimpleNamespace(sandbox_id=str(self.index), metadata={"token": "intent"}, state=SandboxState.RUNNING)
            ]

    def listing(*, query, **kwargs):
        assert isinstance(query, SandboxQuery)
        # Exercise the actual SDK request serializer, including enum states.
        serialized = get_v2_sandboxes._get_kwargs(state=query.state)
        assert serialized["params"]["state"] == "running,paused"
        calls.append((query.metadata, kwargs))
        return Pages()

    monkeypatch.setattr(value._sdk.Sandbox, "list", listing)
    assert len(await value._inventory("intent")) == 2
    assert calls[0][0] == {"namespace": "e2b:tests", "token": "intent"}
    assert calls[0][1]["retries"] == 0


@pytest.mark.asyncio
async def test_stream_bound_closes_reader(monkeypatch):
    import httpx
    from e2b.sandbox.filesystem.filesystem import FileStreamReader

    value = provider()
    response = httpx.Response(200, content=b"too-large")
    stream = FileStreamReader(response)
    files = SimpleNamespace(get_info=lambda *a, **k: SimpleNamespace(size=1), read=lambda *a, **k: stream)
    monkeypatch.setattr(value, "_transport", lambda ref: SimpleNamespace(files=files))
    with pytest.raises(SandboxError, match="byte limit"):
        await value._read("computer", "root-object", max_bytes=2)
    assert stream._closed
