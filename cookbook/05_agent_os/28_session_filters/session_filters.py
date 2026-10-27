"""Search sessions with nested filters and pagination, without a model or API key."""

from tempfile import TemporaryDirectory

from agno.db.sqlite import SqliteDb
from agno.os.routers.session.session import get_session_router
from agno.session import AgentSession, TeamSession
from fastapi import FastAPI
from fastapi.testclient import TestClient

# SQLite keeps this local demonstration self-contained. Use PostgreSQL in production.
with TemporaryDirectory() as directory:
    db = SqliteDb(db_file=f"{directory}/sessions.db")
    db.upsert_session(
        AgentSession(
            session_id="billing-chat",
            agent_id="support",
            user_id="alice",
            session_data={"session_name": "Billing question"},
        )
    )
    db.upsert_session(
        TeamSession(
            session_id="billing-review",
            team_id="support-team",
            user_id="alice",
            session_data={"session_name": "Billing review"},
        )
    )

    app = FastAPI()
    app.include_router(get_session_router({"demo": [db]}))
    with TestClient(app) as client:
        response = client.post(
            "/sessions/search?db_id=demo",
            json={
                "filter": {
                    "op": "AND",
                    "conditions": [
                        {"op": "EQ", "key": "user_id", "value": "alice"},
                        {"op": "CONTAINS", "key": "session_name", "value": "billing"},
                    ],
                },
                "page": 1,
                "limit": 1,
                "sort_by": "created_at",
                "sort_order": "desc",
            },
        )
        response.raise_for_status()
        result = response.json()
        assert len(result["data"]) == 1
        assert result["meta"]["total_count"] == 2
        assert result["meta"]["total_pages"] == 2
        print(result)
