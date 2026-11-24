"""External SDK identity is consistent across session and run read APIs."""

from copy import deepcopy

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agno.db.base import AsyncBaseDb, SessionType
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.os.routers.session.session import get_session_router
from agno.os.schema import AgentSessionDetailSchema, RunSchema, SessionSchema
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession


async def call_db(db, method, **kwargs):
    result = getattr(db, method)(**kwargs)
    return await result if isinstance(db, AsyncBaseDb) else result


@pytest_asyncio.fixture(params=[SqliteDb, AsyncSqliteDb], ids=["sync-db", "async-db"])
async def api(request, tmp_path):
    db = request.param(id="test-db", db_file=str(tmp_path / "sessions.db"), session_table="agno_sessions")
    app = FastAPI()
    app.include_router(get_session_router({"test-db": [db]}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, db
    if isinstance(db, AsyncBaseDb):
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent_data, sdk",
    [
        ({"sdk": "codex"}, "codex"),
        ({"sdk": "claude-agent-sdk"}, "claude-agent-sdk"),
        ({"sdk": "langgraph"}, "langgraph"),
        ({"framework": "claude-agent-sdk"}, "claude-agent-sdk"),
        ({"framework": "codex", "sdk": "custom"}, "custom"),
        ({"agent_name": "Native agent"}, None),
        (None, None),
    ],
)
async def test_sdk_in_list_detail_and_runs_preserves_stored_metadata(api, agent_data, sdk):
    client, db = api
    session = AgentSession(
        session_id="s", agent_id="a", agent_data=agent_data, metadata={"label": "keep"}, created_at=100
    )
    run = RunOutput(
        run_id="r",
        session_id="s",
        agent_id="a",
        status=RunStatus.completed,
        metadata={"request": "keep"},
        content="done",
        created_at=100,
    )
    await call_db(db, "upsert_session", session=session)
    await call_db(db, "upsert_run", run=run, session_id="s")
    params = {"db_id": "test-db", "table": "agno_sessions", "type": "agent"}
    response = await client.get("/sessions", params={**params, "page": 1, "limit": 25, "sort_by": "updated_at"})
    assert response.status_code == 200, response.text
    expected_session = {"label": "keep", **({"sdk": sdk} if sdk else {})}
    assert response.json()["data"][0]["metadata"] == expected_session
    response = await client.get("/sessions/s", params=params)
    assert response.status_code == 200, response.text
    assert response.json()["metadata"] == expected_session
    expected_run = {"request": "keep", **({"sdk": sdk} if sdk else {})}
    response = await client.get("/sessions/s/runs", params=params)
    assert response.status_code == 200, response.text
    assert response.json()[0]["metadata"] == expected_run
    response = await client.get("/sessions/s/runs/r", params=params)
    assert response.status_code == 200, response.text
    assert response.json()["metadata"] == expected_run

    # Type auto-detection uses the same metadata enrichment.
    response = await client.get("/sessions/s/runs", params={"db_id": "test-db"})
    assert response.status_code == 200, response.text
    assert response.json()[0]["metadata"] == expected_run
    stored = await call_db(db, "get_session", session_id="s", session_type=SessionType.AGENT)
    assert stored.metadata == {"label": "keep"}
    assert stored.agent_data == agent_data
    assert stored.runs[0].metadata == {"request": "keep"}


def test_sdk_identity_does_not_mutate_metadata_or_leak_to_member_runs():
    session = {"session_id": "s", "session_type": "agent", "agent_id": "a", "agent_data": {"sdk": "codex"}}
    metadata = {"sdk": "user-value", "nested": {"keep": True}}
    run = {"run_id": "r", "agent_id": "a", "metadata": metadata}
    original = deepcopy(run)
    assert RunSchema.from_dict(run, session=session).metadata == {"sdk": "codex", "nested": {"keep": True}}
    assert run == original
    assert RunSchema.from_dict({"run_id": "child", "agent_id": "other"}, session=session).metadata is None
    assert SessionSchema.from_dict({**session, "metadata": metadata}).metadata["sdk"] == "codex"
    assert metadata == original["metadata"]


@pytest.mark.parametrize("session_type", ["team", "workflow"])
def test_non_agent_sessions_do_not_inherit_sdk(session_type):
    session = {
        "session_id": "s",
        "session_type": session_type,
        f"{session_type}_id": "component",
        "agent_data": {"sdk": "codex"},
        "metadata": {"label": "keep"},
    }
    assert SessionSchema.from_dict(session).metadata == {"label": "keep"}
    assert RunSchema.from_dict({"run_id": "member", "agent_id": "a"}, session=session).metadata is None


@pytest.mark.parametrize("agent_data", ["codex", ["codex"], 7, {"sdk": None}, {"sdk": 3}])
def test_malformed_agent_data_means_no_label_not_a_failed_read(agent_data):
    session = {"session_id": "s", "session_type": "agent", "agent_id": "a", "agent_data": agent_data}
    assert SessionSchema.from_dict({**session, "metadata": {"label": "keep"}}).metadata == {"label": "keep"}
    assert RunSchema.from_dict({"run_id": "r", "agent_id": "a"}, session=session).metadata is None


def test_native_runs_without_metadata_remain_unlabelled():
    run = RunSchema.from_dict({"run_id": "native", "agent_id": "a"})
    assert "metadata" not in run.model_dump(exclude_none=True)


def test_sdk_metadata_is_created_when_stored_metadata_is_absent():
    from agno.agents.codex import CodexAgent
    from agno.os.schema import AgentSummaryResponse

    agent = CodexAgent(id="a")
    session = agent._create_session("s")
    session.metadata = None
    expected = AgentSummaryResponse.from_agent(agent).metadata
    assert expected == {"sdk": "codex"}
    assert SessionSchema.from_dict(session.to_dict()).metadata == expected
    assert AgentSessionDetailSchema.from_session(session).metadata == expected
    assert RunSchema.from_dict({"run_id": "r", "agent_id": "a"}, session=session.to_dict()).metadata == expected
    assert session.metadata is None
