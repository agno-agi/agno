"""Behavior of Remote* classes when the backing server is unreachable.

Metadata degrades gracefully (error log + placeholder or None) so a hosting AgentOS
can boot and serve; runs still fail loudly with RemoteServerUnavailableError.
"""

import httpx
import pytest

from agno.agent.remote import RemoteAgent
from agno.exceptions import RemoteServerUnavailableError
from agno.team.remote import RemoteTeam
from agno.utils.http import set_default_async_client, set_default_sync_client


def _refuse_connection(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


@pytest.fixture(autouse=True)
def offline_http_clients():
    """Point both default httpx clients at a transport that refuses every connection."""
    set_default_sync_client(httpx.Client(transport=httpx.MockTransport(_refuse_connection)))
    set_default_async_client(httpx.AsyncClient(transport=httpx.MockTransport(_refuse_connection)))
    yield
    set_default_sync_client(httpx.Client())
    set_default_async_client(httpx.AsyncClient())


def test_remote_agent_metadata_degrades_when_offline():
    agent = RemoteAgent(base_url="http://offline-host", agent_id="a-1")

    assert agent._agent_config is None
    assert agent.name == "a-1"
    assert agent.description == ""
    assert agent.tools is None
    assert agent.db is None
    assert agent.knowledge is None
    # Failures are not cached, so recovery is immediate once the server is back
    assert agent._cached_agent_config is None


def test_remote_team_metadata_degrades_when_offline():
    team = RemoteTeam(base_url="http://offline-host", team_id="t-1")

    assert team._team_config is None
    assert team.name == "t-1"
    assert team.description == ""
    assert team.tools is None
    assert team.db is None
    assert team.knowledge is None
    assert team._cached_team_config is None


@pytest.mark.asyncio
async def test_remote_agent_config_placeholder_when_offline():
    agent = RemoteAgent(base_url="http://offline-host", agent_id="a-1")

    config = await agent.get_agent_config()

    assert config.id == "a-1"
    assert config.name == "a-1"
    assert config.description == "RemoteAgent is unreachable, likely offline"


@pytest.mark.asyncio
async def test_remote_team_config_placeholder_when_offline():
    team = RemoteTeam(base_url="http://offline-host", team_id="t-1")

    config = await team.get_team_config()

    assert config.id == "t-1"
    assert config.name == "t-1"
    assert config.description == "RemoteTeam is unreachable, likely offline"


@pytest.mark.asyncio
async def test_runs_still_fail_loudly_when_offline():
    agent = RemoteAgent(base_url="http://offline-host", agent_id="a-1")

    with pytest.raises(RemoteServerUnavailableError):
        await agent.arun("hi")


def test_agent_os_boots_with_unreachable_remote_entities():
    from agno.os import AgentOS

    agent_os = AgentOS(
        id="offline-boot-os",
        agents=[RemoteAgent(base_url="http://offline-host", agent_id="a-1")],
        teams=[RemoteTeam(base_url="http://offline-host", team_id="t-1")],
        telemetry=False,
    )
    app = agent_os.get_app()

    assert app is not None
    # No remote dbs could be discovered, but the OS is up and serving
    assert agent_os.dbs == {}
