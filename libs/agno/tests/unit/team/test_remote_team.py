from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.agent.remote import RemoteAgent
from agno.team.remote import RemoteTeam


def test_remote_team_exposes_knowledge_filter_attributes() -> None:
    remote_team = RemoteTeam.__new__(RemoteTeam)
    remote_team.agentos_client = None

    assert remote_team.knowledge_filters is None
    assert remote_team.enable_agentic_knowledge_filters is False
    assert (not remote_team.knowledge_filters and remote_team.knowledge) is None


@pytest.mark.asyncio
async def test_remote_agent_a2a_forwards_metadata() -> None:
    """RemoteAgent.arun(protocol="a2a") must forward `metadata` to the A2A client.

    Regression test: metadata was accepted by arun()'s signature but silently
    dropped before reaching a2a_client.send_message/stream_message.
    """
    remote_agent = RemoteAgent(base_url="http://fake-host", agent_id="test_agent", protocol="a2a")

    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(return_value=MagicMock())
    remote_agent.a2a_client = mock_client

    await remote_agent.arun(
        "hello",
        stream=False,
        user_id="user-123",
        session_id="session-abc",
        metadata={"company_id": "C-1", "investor_company_id": "IC-1"},
        auth_token="jwt-token-here",
    )

    mock_client.send_message.assert_called_once()
    assert mock_client.send_message.call_args.kwargs["metadata"] == {
        "company_id": "C-1",
        "investor_company_id": "IC-1",
    }


@pytest.mark.asyncio
async def test_remote_team_a2a_forwards_metadata() -> None:
    """RemoteTeam.arun(protocol="a2a") must forward `metadata` to the A2A client.

    Regression test: same drop as RemoteAgent, mirrored in RemoteTeam._arun_a2a.
    """
    remote_team = RemoteTeam(base_url="http://fake-host", team_id="test_team", protocol="a2a")

    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(return_value=MagicMock())
    remote_team.a2a_client = mock_client

    await remote_team.arun(
        "hello",
        stream=False,
        user_id="user-123",
        session_id="session-abc",
        metadata={"company_id": "C-1", "investor_company_id": "IC-1"},
        auth_token="jwt-token-here",
    )

    mock_client.send_message.assert_called_once()
    assert mock_client.send_message.call_args.kwargs["metadata"] == {
        "company_id": "C-1",
        "investor_company_id": "IC-1",
    }
