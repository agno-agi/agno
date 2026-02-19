from unittest.mock import AsyncMock, patch

import pytest

from agno.client import AgentOSClient
from agno.db.base import SessionType


@pytest.mark.asyncio
async def test_run_agent_serializes_empty_string_user_id():
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {"run_id": "run-1", "agent_id": "a-1", "content": "ok", "created_at": 0}
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_data
        await client.run_agent(agent_id="a-1", message="hi", user_id="", session_id="")

        form_data = mock_post.call_args[0][1]
        assert form_data["user_id"] == ""
        assert form_data["session_id"] == ""


@pytest.mark.asyncio
async def test_run_agent_omits_none_user_id():
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {"run_id": "run-1", "agent_id": "a-1", "content": "ok", "created_at": 0}
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_data
        await client.run_agent(agent_id="a-1", message="hi")

        form_data = mock_post.call_args[0][1]
        assert "user_id" not in form_data
        assert "session_id" not in form_data


@pytest.mark.asyncio
async def test_delete_session_includes_user_id_in_params():
    client = AgentOSClient(base_url="http://localhost:7777")
    with patch.object(client, "_adelete", new_callable=AsyncMock) as mock_delete:
        await client.delete_session("sess-1", user_id="alice")

        params = mock_delete.call_args.kwargs["params"]
        assert params["user_id"] == "alice"


@pytest.mark.asyncio
async def test_delete_session_omits_user_id_when_none():
    client = AgentOSClient(base_url="http://localhost:7777")
    with patch.object(client, "_adelete", new_callable=AsyncMock) as mock_delete:
        await client.delete_session("sess-1")

        params = mock_delete.call_args.kwargs.get("params", {})
        assert "user_id" not in params


@pytest.mark.asyncio
async def test_delete_sessions_includes_user_id_in_params():
    client = AgentOSClient(base_url="http://localhost:7777")
    with patch.object(client, "_adelete", new_callable=AsyncMock) as mock_delete:
        await client.delete_sessions(
            session_ids=["s-1"],
            session_types=[SessionType.AGENT],
            user_id="alice",
        )

        params = mock_delete.call_args.kwargs["params"]
        assert params["user_id"] == "alice"


@pytest.mark.asyncio
async def test_rename_session_includes_user_id_in_params():
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "agent_session_id": "as-1",
        "session_id": "sess-1",
        "session_name": "Renamed",
        "agent_id": "a-1",
        "user_id": "alice",
    }
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_data
        await client.rename_session("sess-1", "Renamed", user_id="alice")

        params = mock_post.call_args.kwargs["params"]
        assert params["user_id"] == "alice"
