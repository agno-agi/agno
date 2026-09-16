"""No auth + user_isolation=True: every request that touches user data must name its user.

Before, the no-auth identity middleware scoped a request only when ``?user_id=`` was present, so a
request that omitted it read everyone's data: omission was a bypass. Now the flag is on for every
request and a scoped read with no id is refused (400). Runs name their user in the form body, which
the middleware never reads, so the run routes adopt that value as the identity before scoping.
With the flag off nothing changes.
"""

import time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy")

from agno.agent import Agent  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.middleware.user_scope import MISSING_SELF_ASSERTED_USER_ID  # noqa: E402
from agno.session import AgentSession  # noqa: E402


class _Out:
    def to_dict(self):
        return {"run_id": "r1", "content": "ok", "status": "COMPLETED"}


def _served(tmp_path, *, user_isolation: bool):
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    agent = Agent(id="research-agent", name="R", db=db)
    os_ = AgentOS(id="iso-os", db=db, agents=[agent], user_directory=True, user_isolation=user_isolation)
    for user in ("alice", "alice", "bob"):
        db.upsert_session(
            AgentSession(
                session_id=f"{user}-{uuid4().hex[:6]}",
                agent_id="research-agent",
                user_id=user,
                created_at=int(time.time()),
                updated_at=int(time.time()),
            )
        )
    return TestClient(os_.get_app()), os_, db


def _run(client, *, query_user=None, form_user=None):
    q = f"?user_id={query_user}" if query_user else ""
    data = {"message": "hi", "stream": "false"}
    if form_user:
        data["user_id"] = form_user
    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _Out()
        return client.post(f"/agents/research-agent/runs{q}", data=data)


def test_id_less_reads_are_refused_and_named_reads_are_scoped(tmp_path):
    client, _, _ = _served(tmp_path, user_isolation=True)

    r = client.get("/sessions?type=agent")
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == MISSING_SELF_ASSERTED_USER_ID

    assert sorted(s["user_id"] for s in client.get("/sessions?type=agent&user_id=alice").json()["data"]) == [
        "alice",
        "alice",
    ]
    assert [s["user_id"] for s in client.get("/sessions?type=agent&user_id=bob").json()["data"]] == ["bob"]

    # the catalog scopes too (a DB-registered component is a user's), so it needs the id as well
    assert client.get("/agents").status_code == 400
    assert [a["id"] for a in client.get("/agents?user_id=alice").json()] == ["research-agent"]

    # a reserved principal is treated as absent, so it is refused the same way rather than adopted
    assert client.get("/sessions?type=agent&user_id=__scheduler__").status_code == 400


def test_runs_take_the_form_user_id_as_identity(tmp_path):
    """The middleware reads only the query. A run that names its user in the form (how every
    client sends it) must still work and register the person, and must be pinned to that user."""
    client, os_, _ = _served(tmp_path, user_isolation=True)

    ok = _run(client, form_user="carol")
    assert ok.status_code == 200, ok.text
    assert os_.user_directory.user_store.get("carol") is not None  # provisioned from the run

    # query and form both present: the query is the identity, and a differing form is not a way
    # to attribute the run to someone else (the run route already pins to the scoped id)
    assert _run(client, query_user="carol", form_user="alice").status_code == 200

    # a run that names nobody at all is refused like any other id-less request
    nobody = _run(client)
    assert nobody.status_code == 400, nobody.text
    assert nobody.json()["detail"] == MISSING_SELF_ASSERTED_USER_ID

    # a reserved principal in the form is refused, not adopted
    assert _run(client, form_user="sa:backend").status_code == 403


def test_flag_off_is_unchanged(tmp_path):
    """Without user_isolation the no-auth OS serves reads unscoped and runs by their form id."""
    client, os_, _ = _served(tmp_path, user_isolation=False)
    assert client.get("/sessions?type=agent").json()["meta"]["total_count"] == 3
    assert client.get("/agents").status_code == 200
    assert _run(client, form_user="dave").status_code == 200
    assert os_.user_directory.user_store.get("dave") is not None
